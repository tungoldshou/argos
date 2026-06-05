"""启动 logo 画面(spec §启动画面)。ASCII ARGOS + 模型档 + 诚实模式徽标 + 版本 + 提示。
plan mode 时标题前缀 [plan mode] + 切色(spec §2.4),set_plan_mode() 切换。"""
from __future__ import annotations

from textual.reactive import reactive
from textual.widgets import Static

try:
    from importlib.metadata import version as _v
    _VERSION = _v("argos")
except Exception:  # noqa: BLE001
    _VERSION = "0.x"

_LOGO = r"""
   █████╗ ██████╗  ██████╗  ██████╗ ███████╗
  ██╔══██╗██╔══██╗██╔════╝ ██╔═══██╗██╔════╝
  ███████║██████╔╝██║  ███╗██║   ██║███████╗
  ██╔══██╗██╔══██╗██║   ██║██║   ██║╚════██║
  ██║  ██║██║  ██║╚██████╔╝╚██████╔╝███████║
  ╚═╝  ╚═╝╚═╝  ╚═╝ ╚═════╝  ╚═════╝ ╚══════╝
"""

_PLAN_PREFIX = "[plan mode] "


def _compose_text(*, model_label: str, live: bool, plan_mode: bool) -> str:
    mode = "✳ LIVE" if live else "⚠ DEMO 演示"
    prefix = _PLAN_PREFIX if plan_mode else ""
    return prefix + (
        _LOGO
        # ASCII art 是块字符,不含可检索的字面 "ARGOS" —— 补一行字面 wordmark,
        # 既让 renderable_text 含 "ARGOS"(测试断言/可访问性文本),又作品牌行。
        + "\n                   ARGOS\n"
        + f"\n     终端超级智能体 · v{_VERSION}\n\n"
        + f"     模型 {model_label} · {mode}\n"
        + "     输入目标开始,或输入 / 看命令  ·  ^C 退出"
    )


class StartupSplash(Static):
    DEFAULT_CSS = """
    StartupSplash { content-align: center middle; height: auto; padding: 2 0; color: $accent; }
    StartupSplash.-plan-mode { color: $primary; }
    """
    # plan_mode:实时反映当前 plan mode 状态。set_plan_mode() 是 host 侧切换入口,
    # watch_ 触发重渲(前缀 + 切色)。text 字段保留便于 renderable_text / 测试断言。
    plan_mode: reactive[bool] = reactive(False)

    def __init__(self, *, model_label: str, tier: str, live: bool) -> None:
        self._model_label = model_label
        self._tier = tier
        self._live = live
        self._text = _compose_text(
            model_label=model_label, live=live, plan_mode=False,
        )
        super().__init__(self._text)

    def set_plan_mode(self, active: bool) -> None:
        """host 切换入口:切前缀 + 切色。"""
        self.plan_mode = bool(active)

    def _refresh(self) -> None:
        self._text = _compose_text(
            model_label=self._model_label, live=self._live,
            plan_mode=self.plan_mode,
        )
        self.update(self._text)
        # 切色 CSS 类:plan mode 走 $primary 冷靛蓝(对齐 glow.phase_color("plan")),act 走 $accent
        self.set_class(self.plan_mode, "-plan-mode")

    def watch_plan_mode(self, value: bool) -> None:  # noqa: ARG002 — Textual 回调签名
        self._refresh()

    @property
    def renderable_text(self) -> str:
        return self._text
