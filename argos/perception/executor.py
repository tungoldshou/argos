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
import struct
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from argos.i18n import t as _t

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

# 诚实消息:lazily resolved via i18n at call site


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

def detect_scale_factor(
    *,
    screenshot_width: int,
    logical_width: int,
) -> float:
    """计算 Retina 屏幕的 backing scale factor。

    原理:screencapture -x 返回**物理像素**宽度;System Events/AppleScript 的坐标空间
    使用**逻辑点**宽度(HiDPI 下为物理像素的 1/scale)。scale = physical / logical。

    参数:
      screenshot_width — screencapture 返回的 PNG 像素宽度(物理像素)。
      logical_width    — 显示器逻辑宽度(点);来自 system_profiler / CoreGraphics。

    返回:
      float — 缩放因子,通常为 1.0(1x)或 2.0(Retina 2x)。
      0 logical_width 时 fallback 为 1.0(避免除零)。

    此函数是纯数学计算:不做 IO、可单测(不依赖真实显示器)。
    """
    if logical_width <= 0:
        return 1.0
    return float(screenshot_width) / float(logical_width)


def _png_width(path: str) -> int | None:
    """从 PNG 文件头读取像素宽度(IHDR chunk,字节 16-20 big-endian),不依赖 PIL。"""
    try:
        with open(path, "rb") as f:
            head = f.read(24)
        if head[:8] != b"\x89PNG\r\n\x1a\n":
            return None
        return struct.unpack(">I", head[16:20])[0]
    except Exception:  # noqa: BLE001 — 探测失败回退,不抛
        return None


_SCALE_CACHE: dict[str, float] = {}


def detect_display_scale() -> float:
    """探测主显示器 backing scale factor(物理像素 / 逻辑点)。仅 macOS;任何失败回退 1.0
    (= 现状,零回归)。无 pyobjc 依赖:osascript 取桌面逻辑宽,screencapture + PNG 头取物理宽。
    模块级缓存:每进程只探一次(避免每次 dispatch 重复截图闪屏)。Retina(2x)返 2.0。"""
    if "scale" in _SCALE_CACHE:
        return _SCALE_CACHE["scale"]
    scale = 1.0
    if sys.platform == "darwin":
        try:
            # 逻辑宽:Finder desktop bounds → "0, 0, 1440, 900"(第 3 个数 = 逻辑宽)
            r = subprocess.run(
                ["osascript", "-e",
                 'tell application "Finder" to get bounds of window of desktop'],
                capture_output=True, text=True, timeout=5,
            )
            logical_w = 0
            if r.returncode == 0:
                nums = [int(p.strip()) for p in r.stdout.strip().split(",")
                        if p.strip().lstrip("-").isdigit()]
                if len(nums) >= 3:
                    logical_w = nums[2]
            # 物理宽:截一张临时图读 PNG 头宽(screencapture -x 不含指针)
            physical_w = 0
            if logical_w > 0:
                with tempfile.NamedTemporaryFile(suffix=".png", delete=True) as tf:
                    sc = subprocess.run(["screencapture", "-x", tf.name],
                                        capture_output=True, timeout=_SCREENSHOT_TIMEOUT)
                    if sc.returncode == 0:
                        w = _png_width(tf.name)
                        if w:
                            physical_w = w
            if logical_w > 0 and physical_w > 0:
                scale = detect_scale_factor(screenshot_width=physical_w, logical_width=logical_w)
        except Exception:  # noqa: BLE001 — 探测失败回退 1.0(不破坏点击,只是不缩放)
            scale = 1.0
    _SCALE_CACHE["scale"] = scale
    return scale


class ComputerExecutor:
    """零依赖 macOS 后端:把 ComputerAction 映射到系统命令。

    构造时不做任何 IO;每次 dispatch() 调用独立执行并返回 ComputerActionResult。

    能力开关:
      ARGOS_COMPUTER_USE=1  (env) — 未设置则所有动作返回诚实禁止消息。

    Retina 缩放:
      screencapture -x 返回物理像素坐标,但 AppleScript System Events 接受逻辑点。
      在 2x Retina 显示器上物理像素 = 逻辑点 × 2,直接传物理坐标会导致点击偏移到
      约 2 倍位置。scale_factor 参数用于在传给 osascript 前将坐标除以该因子。

      · 默认 scale_factor=1.0:1x 显示器或已在逻辑点空间的坐标。
      · 注入 scale_factor=2.0:2x Retina;测试可直接注入,无需真实显示器。
      · 生产路径:由调用方用 detect_scale_factor(screenshot_width, logical_width)
        计算后注入(或在 dispatch 前动态查询 logical_width)。
    """

    def __init__(self, *, timeout: int = _DEFAULT_TIMEOUT, scale_factor: float = 1.0,
                 auto_detect_scale: bool = False) -> None:
        """
        参数:
          timeout           — 每个动作的超时秒数(截图单独用 _SCREENSHOT_TIMEOUT)。
          scale_factor      — Retina backing scale factor(物理像素 / 逻辑点)。
                              1.0 = 1x 显示器(默认,坐标不变);2.0 = 2x Retina。
                              可注入以便单测不依赖真实显示器。
          auto_detect_scale — True 时在首个点击/滚动动作(且 ARGOS_COMPUTER_USE 开)惰性探测
                              真实显示器 scale 覆盖 scale_factor(detect_display_scale,模块级缓存)。
                              生产 dispatch 路径置 True;构造默认 False → 单测/非 CU 路径行为不变。
        """
        self._timeout = timeout
        self._scale_factor = scale_factor
        self._auto_detect_scale = auto_detect_scale
        self._scale_resolved = False  # 惰性探测只跑一次的闸

    def _effective_scale(self) -> float:
        """返回生效的 scale factor。auto_detect_scale 且 computer-use 已开时,首次惰性探测真实
        显示器并缓存进 self._scale_factor(失败回退 1.0)。显式注入 scale_factor 时不探测。"""
        if (self._auto_detect_scale and not self._scale_resolved
                and os.environ.get("ARGOS_COMPUTER_USE")):
            self._scale_factor = detect_display_scale()
            self._scale_resolved = True
        return self._scale_factor

    # ── 公开入口 ──────────────────────────────────────────────────────────────

    def dispatch(self, action: "ComputerAction") -> ComputerActionResult:
        """执行 action 并返回结果。

        能力未启用时立即返回诚实错误。
        各 kind 委托对应私有方法处理。
        """
        if os.environ.get(_ENV_FLAG, "") != "1":
            return ComputerActionResult(ok=False, detail=_t("perception.executor.disabled"))

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
                detail=_t("perception.executor.unknown_kind", kind=kind),
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
            return -1, "", _t("perception.executor.timeout", cmd=cmd[0], t=t)
        except FileNotFoundError:
            return -1, "", _t("perception.executor.cmd_not_found", cmd=cmd[0])

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
                detail=_t("perception.executor.screenshot_failed",
                          rc=rc, err=err.strip() or _t("perception.executor.unknown_error")),
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
            detail=_t("perception.executor.screenshot_saved", path=path),
            artifact_path=path,
            size=size,
        )

    def _click(self, x: int | None, y: int | None, *, double: bool) -> ComputerActionResult:
        """在 (x, y) 处单击或双击(System Events via osascript)。

        坐标单位:调用方传入的是截图中的像素坐标(物理像素)。
        Retina 显示器上 screencapture 返回物理像素,但 System Events 接受逻辑点,
        因此在传给 AppleScript 前除以 scale_factor 换算为逻辑点。
        """
        action_word = "double click" if double else "click"
        # 物理像素 → 逻辑点(scale=1.0 时不变,scale=2.0 时减半)
        _scale = self._effective_scale()
        lx = round(x / _scale) if x is not None else x
        ly = round(y / _scale) if y is not None else y
        script = (
            f'tell application "System Events"\n'
            f'    {action_word} at {{x:{lx}, y:{ly}}}\n'
            f'end tell'
        )
        rc, out, err = self._run(["osascript", "-e", script])
        if rc != 0:
            if _is_access_denied(err, out):
                return ComputerActionResult(ok=False, detail=_t("perception.executor.access_denied"))
            _err_str = err.strip() or out.strip() or _t("perception.executor.unknown_error")
            _key = "perception.executor.double_click_failed" if double else "perception.executor.click_failed"
            return ComputerActionResult(
                ok=False,
                detail=_t(_key, rc=rc, err=_err_str),
            )
        _ok_key = "perception.executor.double_click_ok" if double else "perception.executor.click_ok"
        return ComputerActionResult(
            ok=True,
            detail=_t(_ok_key, lx=lx, ly=ly),
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
                return ComputerActionResult(ok=False, detail=_t("perception.executor.access_denied"))
            return ComputerActionResult(
                ok=False,
                detail=_t("perception.executor.type_text_failed",
                           rc=rc, err=err.strip() or out.strip() or _t("perception.executor.unknown_error")),
            )
        preview = text[:40] + ("…" if len(text) > 40 else "")
        return ComputerActionResult(ok=True, detail=_t("perception.executor.type_text_ok", preview=preview))

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
                return ComputerActionResult(ok=False, detail=_t("perception.executor.access_denied"))
            return ComputerActionResult(
                ok=False,
                detail=_t("perception.executor.key_failed",
                           rc=rc, err=err.strip() or out.strip() or _t("perception.executor.unknown_error")),
            )
        return ComputerActionResult(ok=True, detail=_t("perception.executor.key_ok", combo=key_combo))

    def _scroll(self, x: int | None, y: int | None, dy: int) -> ComputerActionResult:
        """在 (x, y) 处滚动 dy 行(System Events scroll)。

        同 _click:坐标除以 scale 换算为逻辑点后再传给 AppleScript。
        """
        _scale = self._effective_scale()
        lx = round(x / _scale) if x is not None else x
        ly = round(y / _scale) if y is not None else y
        script = (
            f'tell application "System Events"\n'
            f'    scroll (a reference to the front window) by {dy} using at {{x:{lx}, y:{ly}}}\n'
            f'end tell'
        )
        rc, out, err = self._run(["osascript", "-e", script])
        if rc != 0:
            if _is_access_denied(err, out):
                return ComputerActionResult(ok=False, detail=_t("perception.executor.access_denied"))
            return ComputerActionResult(
                ok=False,
                detail=_t("perception.executor.scroll_failed",
                           rc=rc, err=err.strip() or out.strip() or _t("perception.executor.unknown_error")),
            )
        return ComputerActionResult(ok=True, detail=_t("perception.executor.scroll_ok", lx=lx, ly=ly, dy=dy))

    def _open_app(self, app: str) -> ComputerActionResult:
        """用 `open -a` 打开应用。"""
        rc, _out, err = self._run(["open", "-a", app])
        if rc != 0:
            return ComputerActionResult(
                ok=False,
                detail=_t("perception.executor.open_app_failed",
                           app=app, rc=rc,
                           err=err.strip() or _t("perception.executor.open_app_no_permission")),
            )
        return ComputerActionResult(ok=True, detail=_t("perception.executor.open_app_ok", app=app))
