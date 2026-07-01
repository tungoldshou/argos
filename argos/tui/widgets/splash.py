"""启动 logo 画面(TUI v3 spec §4.2:睁眼仪式)。▄▀█ 像素风块字 ARGOS + 状态眼 + 两行信息。

v3 变更:
- 旧 box-drawing 巨眼 logo(╔╗╚╝)裁决判死,改为 ▄▀█ 像素风块字
- 状态眼单行:◌/◔/◓/◉ 随 advance_eye(stage) 推进睁眼仪式
- 无 key 永远停在 ◌,绝不出现 LIVE(契约6)
- 新增 advance_eye(stage) 方法驱动睁眼仪式

v4 着色修正(design-audit 2026-06-14 MEDIUM fix):
- 各段落改用 Rich markup 着色,markup=True 渲染
- 眼 ◉ → $eye-glow (#F0C078)
- 副标题行(版本/模型) → $ink-dim (#7E869C)
- LIVE 徽标 → $pass (#9ECE6A)
- 真相不确定 / unverifiable → $unverif (#FF9E64)
- 提示行 → $ink-faint (#6B7494)
- DEFAULT_CSS 不再写死 color: $ink-bright;CSS 槽只控制布局
"""
from __future__ import annotations

from textual.reactive import reactive
from textual.widgets import Static

from argos.i18n import t

try:
    # 单一来源 argos.__version__(查分发名 "argos-agent" + VERSION 文件兜底)。
    # 不能用 version("argos") —— 分发名非 "argos",必 PackageNotFoundError 回退占位符。
    from argos import __version__ as _VERSION
except Exception:  # noqa: BLE001
    _VERSION = "0.x"

# Rich markup 着色常量 — DEFAULT_CSS 用 $token 名;Rich Text 必须用 hex(Rich 不解析 $token)
# 对应关系与 theme.py 完全一致,勿改
_COL_EYE_GLOW = "#F0C078"   # $eye-glow:呼吸光峰值/眼高亮(logo 焦点金)
_COL_INK_DIM  = "#7E869C"   # $ink-dim:次要/元信息/副标题
_COL_INK_FAINT = "#6B7494"  # $ink-faint:键提示/占位符/提示行(finding #27 升对比度)
_COL_PASS     = "#9ECE6A"   # $pass:verdict passed / LIVE 徽标
_COL_UNVERIF  = "#FF9E64"   # $unverif:DEMO 脚本演示 / 真相不确定

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
    """根据 has_key 状态和睁眼阶段返回当前状态眼字形。

    规则(spec §4.2):
    - 无 key → 永远停在 ◌(不见真相眼不睁)
    - 有 key → 随 _eye_stage 推进;终态 ◉
    live 参数惰性保留(DEMO 已移除,2026-07-01;入参留作测试构造点兼容)。
    """
    if not has_key:
        return "◌"
    return _EYE_STAGES.get(_eye_stage, "◌")


def _compose_text(*, model_label: str, live: bool, plan_mode: bool,
                   has_key: bool = True, eye_stage: str = "init") -> str:
    """组装 splash 渲染文本(Rich markup,markup=True 渲染)。

    二态徽标(诚实底线,契约6):
    - 有 key → ◉ + · LIVE ($pass)
    - has_key=False → ◌ + 未配 key · /setup,绝不出现 LIVE
    live 参数惰性保留(DEMO 已移除,2026-07-01)。

    着色规则(design-audit MEDIUM fix 2026-06-14):
    - 眼字形 → $eye-glow(高亮金,logo 焦点)
    - 副标题行 → $ink-dim
    - LIVE 徽标词 → $pass(绿)
    - 提示行 → $ink-faint
    """
    eye = _eye_for_state(live=live, has_key=has_key, _eye_stage=eye_stage)

    if not has_key:
        # 未配 key:用 ink-dim,绝不出现 LIVE
        badge_markup = f"[{_COL_INK_DIM}]{t('widget.splash_badge_no_key')}[/{_COL_INK_DIM}]"
    else:
        # LIVE:绿色徽标
        badge_markup = f"[{_COL_PASS}]{t('widget.splash_badge_live')}[/{_COL_PASS}]"

    prefix = _plan_prefix_str(plan_mode)
    # 眼字形用 $eye-glow 高亮金;副标题行用 $ink-dim;提示行用 $ink-faint
    # ARGOS wordmark 保留裸文本(无 markup),保证 renderable_text 含 "ARGOS"(测试断言)
    # finding #34:副标题/提示行去掉手工前置空格,改靠 CSS text-align: center 居中。
    # 手工空格在窄终端(<51 cols)会让行在空格处换行,导致副标题错位。
    # logo 块字(_LOGO / "ARGOS" / 眼字形)保留内嵌空格(它们是字形的一部分,非居中手段)。
    return prefix + (
        _LOGO
        + "\n                   ARGOS\n"
        + f"\n                    [{_COL_EYE_GLOW}]{eye}[/{_COL_EYE_GLOW}]\n"
        + f"\n[{_COL_INK_DIM}]{t('widget.splash_subtitle', version=_VERSION)}[/{_COL_INK_DIM}]"
        + badge_markup
        + f"\n[{_COL_INK_FAINT}]{t('widget.splash_hint')}[/{_COL_INK_FAINT}]"
    )


def _plan_prefix_str(plan_mode: bool) -> str:
    """plan mode 时文案首加 'plan · '(spec §4.2)。"""
    return _PLAN_PREFIX if plan_mode else ""


class StartupSplash(Static):
    # DEFAULT_CSS 只控制布局和背景; 各段落颜色通过 Rich markup 着色(_compose_text 内联),
    # 不再用 color: $ink-bright 压一个全局前景色覆盖掉各段差异(design-audit MEDIUM fix)。
    # -plan-mode 仅保留 CSS 类标记,供外部查询用;实际着色由 _compose_text 的 markup 负责。
    # text-align: center(finding #34):逐行居中,避免手工空格在窄终端(<51 cols)换行错位。
    DEFAULT_CSS = """
    StartupSplash { content-align: center middle; text-align: center; height: auto; padding: 1 0; background: $stream; }
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
        # markup=True:启用 Rich markup 解析,使各段颜色生效(design-audit MEDIUM fix)
        super().__init__(self._text, markup=True)

    def advance_eye(self, stage: str) -> None:
        """推进睁眼仪式帧(v3 新增)。

        stage 可取值:'scan'/'half'/'focus'/'open'。
        无 key 时本方法无效(眼永远停在 ◌,契约6)。
        """
        if not self._has_key:
            # 无 key:眼不睁,什么都不做
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
                prefix = t("widget.splash_bad_config_permissions")
            elif "LSP" in reason:
                prefix = t("widget.splash_bad_config_lsp")
            else:
                prefix = t("widget.splash_bad_config_hooks")
            text += f"\n       ⚠︎ {prefix}" + t("widget.splash_bad_config_suffix", reason=reason)
        self._text = text
        self.update(self._text)
        # 切色 CSS 类:plan mode 走 $primary 冷靛蓝(对齐 glow.phase_color("plan")),act 走 $accent
        self.set_class(self.plan_mode, "-plan-mode")

    def watch_plan_mode(self, value: bool) -> None:  # noqa: ARG002 — Textual 回调签名
        self._refresh()

    @property
    def renderable_text(self) -> str:
        return self._text
