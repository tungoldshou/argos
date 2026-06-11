"""启动 logo 画面(TUI v3 spec §4.2:睁眼仪式)。▄▀█ 像素风块字 ARGOS + 状态眼 + 两行信息。

v3 变更:
- 旧 box-drawing 巨眼 logo(╔╗╚╝)裁决判死,改为 ▄▀█ 像素风块字
- 状态眼单行:◌/◔/◓/◉ 随 advance_eye(stage) 推进睁眼仪式
- 无 key 永远停在 ◌,绝不出现 LIVE(契约6)
- DEMO 模式眼停在 ◓
- 新增 advance_eye(stage) 方法驱动睁眼仪式
"""
from __future__ import annotations

from textual.reactive import reactive
from textual.widgets import Static

try:
    from importlib.metadata import version as _v
    _VERSION = _v("argos")
except Exception:  # noqa: BLE001
    _VERSION = "0.x"

# v3: ▄▀█ 像素风块字,无 box-drawing 字符(╔╗╚╝ 等旧字形已裁决判死)
# 两行像素块:ARGOS
_LOGO = (
    "\n"
    "              ▄▀█ █▀█ █▀▀ █▀█ █▀\n"
    "              █▀█ █▀▄ █▄█ █▄█ ▄█\n"
)

# 睁眼仪式帧序列:空态 → 扫视 → 半阖 → 注视(约 0.6s,仅一次,非循环)
_EYE_STAGES: dict[str, str] = {
    "init":  "◌",
    "scan":  "◔",
    "half":  "◓",
    "focus": "◉",
    "open":  "◉",
}

_PLAN_PREFIX = "plan · "


def _eye_for_state(*, live: bool, has_key: bool, _eye_stage: str) -> str:
    """根据 has_key/live 状态和睁眼阶段返回当前状态眼字形。

    规则(spec §4.2):
    - 无 key → 永远停在 ◌(不见真相眼不睁)
    - DEMO(live=False) → 眼停在 ◓(半阖)
    - 有 key → 随 _eye_stage 推进;终态 ◉
    """
    if not has_key:
        return "◌"
    if not live:
        return "◓"
    return _EYE_STAGES.get(_eye_stage, "◌")


def _compose_text(*, model_label: str, live: bool, plan_mode: bool,
                   has_key: bool = True, eye_stage: str = "init") -> str:
    """组装 splash 渲染文本。

    三态徽标(诚实底线,契约6):
    - 有 key + live=True → ◉ + · LIVE
    - live=False → ◓ + DEMO 脚本演示
    - has_key=False → ◌ + 未配 key · /setup,绝不出现 LIVE
    """
    eye = _eye_for_state(live=live, has_key=has_key, _eye_stage=eye_stage)

    if not live:
        badge = "DEMO 脚本演示"
        key_hint = ""
    elif not has_key:
        badge = "未配 key · /setup"
        key_hint = ""
    else:
        badge = "LIVE"
        key_hint = ""

    prefix = _plan_prefix_str(plan_mode)
    # ARGOS 字面 wordmark 在 logo 后追加,保证 renderable_text 含 "ARGOS"(可访问性/测试断言)
    return prefix + (
        _LOGO
        + "\n                   ARGOS\n"
        + f"\n                    {eye}\n"
        + f"\n       终端超级智能体 · v{_VERSION} · {model_label} · {badge}"
        + key_hint
        + "\n       输入目标开始 · / 命令 · Esc 打断 · ^C 退出"
    )


def _plan_prefix_str(plan_mode: bool) -> str:
    """plan mode 时文案首加 'plan · '(spec §4.2)。"""
    return _PLAN_PREFIX if plan_mode else ""


class StartupSplash(Static):
    DEFAULT_CSS = """
    StartupSplash { content-align: center middle; height: auto; padding: 1 0; background: $stream; color: $ink-bright; }
    StartupSplash.-plan-mode { color: $eye-soft; }
    """
    # plan_mode:实时反映当前 plan mode 状态。set_plan_mode() 是 host 侧切换入口,
    # watch_ 触发重渲(前缀 + 切色)。text 字段保留便于 renderable_text / 测试断言。
    plan_mode: reactive[bool] = reactive(False)

    def __init__(self, *, model_label: str, tier: str, live: bool,
                 has_key: bool = True) -> None:
        self._model_label = model_label
        self._tier = tier
        self._live = live
        self._has_key = has_key
        # 睁眼仪式初始阶段:无 key 永远停在 ◌,DEMO 停在 ◓,有 key 从 ◌ 开始推进
        self._eye_stage = "init"
        self._text = _compose_text(
            model_label=model_label, live=live, plan_mode=False,
            has_key=has_key, eye_stage=self._eye_stage,
        )
        super().__init__(self._text)

    def advance_eye(self, stage: str) -> None:
        """推进睁眼仪式帧(v3 新增)。

        stage 可取值:'scan'/'half'/'focus'/'open'。
        无 key 时本方法无效(眼永远停在 ◌,契约6)。
        DEMO 模式眼停在 ◓,不响应 focus/open。
        """
        if not self._has_key:
            # 无 key:眼不睁,什么都不做
            return
        if not self._live and stage in ("focus", "open"):
            # DEMO 最多停在 ◓(半阖)
            return
        self._eye_stage = stage
        self._refresh()

    def set_plan_mode(self, active: bool) -> None:
        """host 切换入口:切前缀 + 切色。"""
        self.plan_mode = bool(active)

    def set_bad_config(self, reason: str) -> None:
        """启动时坏配置 banner(覆盖主标题下一行)。
        reason 来自 HooksConfigError / LspConfigError,简洁一行即可,绝不长段(spec §2.4)。
        reason 串首部含 'LSP' → 显 'LSP 已禁用' 前缀;否则显 'hooks 已禁用'(默认,向后兼容)。"""
        # 存属性;_refresh 时拼到 _text 末尾
        self._bad_config = reason
        self._refresh()

    def _refresh(self) -> None:  # type: ignore[no-redef]
        text = _compose_text(
            model_label=self._model_label, live=self._live,
            plan_mode=self.plan_mode, has_key=self._has_key,
            eye_stage=self._eye_stage,
        )
        if getattr(self, "_bad_config", None):
            # reason 串首部含 'permissions' → 'permissions 已禁用'(spec 2026-06-06 §2.6);
            # 'LSP' → 'LSP 已禁用'(同 hooks/LSP 行为);否则 'hooks 已禁用'(默认)。
            reason = str(self._bad_config)
            if "permissions" in reason:
                prefix = "permissions"
            elif "LSP" in reason:
                prefix = "LSP"
            else:
                prefix = "hooks"
            text += f"\n       ⚠︎ {prefix} 已禁用({reason})"
        self._text = text
        self.update(self._text)
        # 切色 CSS 类:plan mode 走 $primary 冷靛蓝(对齐 glow.phase_color("plan")),act 走 $accent
        self.set_class(self.plan_mode, "-plan-mode")

    def watch_plan_mode(self, value: bool) -> None:  # noqa: ARG002 — Textual 回调签名
        self._refresh()

    @property
    def renderable_text(self) -> str:
        return self._text
