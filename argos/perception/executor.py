"""perception.executor — ComputerAction 的零依赖 macOS 后端。

ComputerExecutor 只用系统自带工具执行 OS 级操作:
  · screenshot  → `screencapture -x <tmp.png>` (静默,不含鼠标指针)
  · click/double_click → AppleScript via `osascript` → System Events
  · type_text   → AppleScript keystroke
  · key         → AppleScript key code / keystroke with modifiers
  · scroll      → AppleScript scroll
  · open_app    → `open -a <app>`

零依赖原则:不引入 pyautogui 或其他第三方库。

诚实性(灵魂):
  · Accessibility 权限未授予时 osascript 返回非零 → ok=False + 人话指引
    ("系统设置 → 隐私与安全性 → 辅助功能 给终端授权"),绝不假装成功。
  · 每个动作带独立 timeout(默认 10 秒),超时返回 ok=False + 诚实描述。
  · ARGOS_COMPUTER_USE=1 才启用 OS 级动作;未启用时 dispatch 返回诚实错误。
  · screenshot/VLM 结果永不单独产出 "passed"——ComputerExecutor 不做验收判断,
    只返回 ok 标志 + detail。

import 说明:
  · PIL/Pillow 仅用于读取截图尺寸(已是 argos 依赖);若不可用则 size=(0,0)。
    executor 本身的截图功能不依赖 PIL,screencapture 可单独工作。
"""
from __future__ import annotations

import os
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from argos.perception.actions import ComputerAction

# ── 常量 ─────────────────────────────────────────────────────────────────────

_DEFAULT_TIMEOUT = 10          # 秒:单个动作执行的硬超时
_SCREENSHOT_TIMEOUT = 15       # 截图允许稍长

# Accessibility 权限拒绝时 osascript 错误输出中的标志字串
_ACCESS_DENIED_MARKERS = (
    "not allowed assistive access",
    "is not allowed to send keystrokes",
    "assistive access",
    "-1719",   # AppleScript error -1719 = can't get element
    "-25211",  # AXError: API Disabled
)

# 能力开关环境变量
_ENV_FLAG = "ARGOS_COMPUTER_USE"

# 诚实消息:未启用 OS 级 computer use
_DISABLED_MSG = (
    "OS 级 computer use 未启用。"
    "如需使用截图/点击等系统控制能力,请设置环境变量 ARGOS_COMPUTER_USE=1 后重启 argos。"
    "注意:此能力操控全局屏幕/鼠标资源,Seatbelt 沙箱无法隔离;"
    "启用前请确认已在系统设置中授予终端辅助功能权限。"
)

# 诚实消息:Accessibility 权限未授予
_ACCESS_DENIED_MSG = (
    "系统拒绝了辅助功能访问请求。"
    "请前往「系统设置 → 隐私与安全性 → 辅助功能」,将终端(Terminal / iTerm / Warp 等)"
    "加入允许列表后重试。截图功能不受此限制。"
)


# ── 结果 dataclass ────────────────────────────────────────────────────────────

@dataclass(frozen=True, slots=True)
class ComputerActionResult:
    """单次 ComputerAction 执行结果。

    ok           — True = 操作成功;False = 失败(detail 含人话原因)
    detail       — 人话说明:成功时为摘要,失败时为错误原因(含权限指引)
    artifact_path — 截图时为 PNG 文件路径,其余为 None
    size         — 截图时为 (width, height),其余为 None
    """
    ok: bool
    detail: str
    artifact_path: str | None = None
    size: tuple[int, int] | None = None


# ── 辅助:检测错误串是否属于权限拒绝 ──────────────────────────────────────────

def _is_access_denied(stderr: str, stdout: str) -> bool:
    """osascript 错误输出中是否含 Accessibility 权限拒绝标志。"""
    combined = (stderr + stdout).lower()
    return any(m in combined for m in _ACCESS_DENIED_MARKERS)


# ── 主 executor ──────────────────────────────────────────────────────────────

class ComputerExecutor:
    """零依赖 macOS 后端:把 ComputerAction 映射到系统命令。

    构造时不做任何 IO;每次 dispatch() 调用独立执行并返回 ComputerActionResult。

    能力开关:
      ARGOS_COMPUTER_USE=1  (env) — 未设置则所有动作返回诚实禁止消息。
    """

    def __init__(self, *, timeout: int = _DEFAULT_TIMEOUT) -> None:
        """
        参数:
          timeout — 每个动作的超时秒数(截图单独用 _SCREENSHOT_TIMEOUT)。
        """
        self._timeout = timeout

    # ── 公开入口 ──────────────────────────────────────────────────────────────

    def dispatch(self, action: "ComputerAction") -> ComputerActionResult:
        """执行 action 并返回结果。

        能力未启用时立即返回诚实错误。
        各 kind 委托对应私有方法处理。
        """
        if os.environ.get(_ENV_FLAG, "") != "1":
            return ComputerActionResult(ok=False, detail=_DISABLED_MSG)

        kind = action.kind
        if kind == "screenshot":
            return self._screenshot()
        elif kind == "click":
            return self._click(action.x, action.y, double=False)
        elif kind == "double_click":
            return self._click(action.x, action.y, double=True)
        elif kind == "type_text":
            return self._type_text(action.text or "")
        elif kind == "key":
            return self._key(action.text or "")
        elif kind == "scroll":
            try:
                dy = int(action.text or "3")
            except ValueError:
                dy = 3
            return self._scroll(action.x, action.y, dy)
        elif kind == "open_app":
            return self._open_app(action.app or "")
        else:
            return ComputerActionResult(
                ok=False,
                detail=f"未知动作 kind={kind!r},拒绝执行。",
            )

    # ── 私有实现 ──────────────────────────────────────────────────────────────

    def _run(
        self,
        cmd: list[str],
        *,
        timeout: int | None = None,
        input_text: str | None = None,
    ) -> tuple[int, str, str]:
        """运行子进程;返回 (returncode, stdout, stderr)。

        超时时 returncode=-1,stderr="timeout"。
        """
        t = timeout if timeout is not None else self._timeout
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=t,
                input=input_text,
            )
            return result.returncode, result.stdout, result.stderr
        except subprocess.TimeoutExpired:
            return -1, "", f"超时:命令 {cmd[0]!r} 在 {t}s 内未完成"
        except FileNotFoundError:
            return -1, "", f"命令不存在: {cmd[0]!r}(请检查 macOS 环境)"

    def _screenshot(self) -> ComputerActionResult:
        """全屏截图 → 临时 PNG 文件;返回路径 + 尺寸。"""
        tmp = tempfile.NamedTemporaryFile(
            suffix=".png", prefix="argos_screen_", delete=False
        )
        tmp.close()
        path = tmp.name

        rc, _out, err = self._run(
            ["screencapture", "-x", path],
            timeout=_SCREENSHOT_TIMEOUT,
        )
        if rc != 0:
            # 删除可能产生的空文件
            try:
                Path(path).unlink(missing_ok=True)
            except OSError:
                pass
            return ComputerActionResult(
                ok=False,
                detail=f"截图失败(exit {rc}): {err.strip() or '未知错误'}",
            )

        # 尝试读取尺寸(Pillow 可选)
        size: tuple[int, int] | None = None
        try:
            from PIL import Image  # type: ignore[import]
            with Image.open(path) as img:
                size = img.size  # (width, height)
        except Exception:
            size = (0, 0)

        return ComputerActionResult(
            ok=True,
            detail=f"截图已保存至 {path}",
            artifact_path=path,
            size=size,
        )

    def _click(self, x: int | None, y: int | None, *, double: bool) -> ComputerActionResult:
        """在 (x, y) 处单击或双击(System Events via osascript)。"""
        action_word = "double click" if double else "click"
        script = (
            f'tell application "System Events"\n'
            f'    {action_word} at {{x:{x}, y:{y}}}\n'
            f'end tell'
        )
        rc, out, err = self._run(["osascript", "-e", script])
        if rc != 0:
            if _is_access_denied(err, out):
                return ComputerActionResult(ok=False, detail=_ACCESS_DENIED_MSG)
            return ComputerActionResult(
                ok=False,
                detail=f"{'双击' if double else '点击'}失败(exit {rc}): {err.strip() or out.strip() or '未知错误'}",
            )
        return ComputerActionResult(
            ok=True,
            detail=f"{'双击' if double else '点击'} ({x}, {y}) 成功",
        )

    def _type_text(self, text: str) -> ComputerActionResult:
        """在当前焦点处键入文本(System Events keystroke)。"""
        # AppleScript 中字符串用引号包裹,双引号需转义
        escaped = text.replace("\\", "\\\\").replace('"', '\\"')
        script = (
            f'tell application "System Events"\n'
            f'    keystroke "{escaped}"\n'
            f'end tell'
        )
        rc, out, err = self._run(["osascript", "-e", script])
        if rc != 0:
            if _is_access_denied(err, out):
                return ComputerActionResult(ok=False, detail=_ACCESS_DENIED_MSG)
            return ComputerActionResult(
                ok=False,
                detail=f"键入文本失败(exit {rc}): {err.strip() or out.strip() or '未知错误'}",
            )
        preview = text[:40] + ("…" if len(text) > 40 else "")
        return ComputerActionResult(ok=True, detail=f"键入文本成功: {preview!r}")

    def _key(self, key_combo: str) -> ComputerActionResult:
        """发送快捷键序列,如 'command+c'、'return'(System Events keystroke using)。

        格式约定:修饰键用 '+' 拼接,如 'command+shift+s'、'control+c'。
        System Events 修饰键关键字:command key / shift key / option key / control key。
        """
        # 解析修饰键 + 主键
        parts = [p.strip().lower() for p in key_combo.split("+")]
        main_key = parts[-1]
        modifiers = parts[:-1]

        modifier_map = {
            "command": "command key",
            "cmd": "command key",
            "shift": "shift key",
            "option": "option key",
            "alt": "option key",
            "control": "control key",
            "ctrl": "control key",
        }
        using_parts = [modifier_map[m] for m in modifiers if m in modifier_map]

        escaped_main = main_key.replace("\\", "\\\\").replace('"', '\\"')
        if using_parts:
            using_clause = " using {" + ", ".join(using_parts) + "}"
        else:
            using_clause = ""

        script = (
            f'tell application "System Events"\n'
            f'    keystroke "{escaped_main}"{using_clause}\n'
            f'end tell'
        )
        rc, out, err = self._run(["osascript", "-e", script])
        if rc != 0:
            if _is_access_denied(err, out):
                return ComputerActionResult(ok=False, detail=_ACCESS_DENIED_MSG)
            return ComputerActionResult(
                ok=False,
                detail=f"快捷键失败(exit {rc}): {err.strip() or out.strip() or '未知错误'}",
            )
        return ComputerActionResult(ok=True, detail=f"快捷键 {key_combo!r} 成功")

    def _scroll(self, x: int | None, y: int | None, dy: int) -> ComputerActionResult:
        """在 (x, y) 处滚动 dy 行(System Events scroll)。"""
        script = (
            f'tell application "System Events"\n'
            f'    scroll (a reference to the front window) by {dy} using at {{x:{x}, y:{y}}}\n'
            f'end tell'
        )
        rc, out, err = self._run(["osascript", "-e", script])
        if rc != 0:
            if _is_access_denied(err, out):
                return ComputerActionResult(ok=False, detail=_ACCESS_DENIED_MSG)
            return ComputerActionResult(
                ok=False,
                detail=f"滚动失败(exit {rc}): {err.strip() or out.strip() or '未知错误'}",
            )
        return ComputerActionResult(ok=True, detail=f"滚动 ({x}, {y}) dy={dy} 成功")

    def _open_app(self, app: str) -> ComputerActionResult:
        """用 `open -a` 打开应用。"""
        rc, _out, err = self._run(["open", "-a", app])
        if rc != 0:
            return ComputerActionResult(
                ok=False,
                detail=f"打开应用 {app!r} 失败(exit {rc}): {err.strip() or '应用不存在或无权限'}",
            )
        return ComputerActionResult(ok=True, detail=f"已启动应用 {app!r}")
