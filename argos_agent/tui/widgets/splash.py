"""启动 logo 画面(spec §启动画面)。ASCII ARGOS + 模型档 + 诚实模式徽标 + 版本 + 提示。"""
from __future__ import annotations

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
  ██╔══██║██╔══██╗██║   ██║██║   ██║╚════██║
  ██║  ██║██║  ██║╚██████╔╝╚██████╔╝███████║
  ╚═╝  ╚═╝╚═╝  ╚═╝ ╚═════╝  ╚═════╝ ╚══════╝
"""


class StartupSplash(Static):
    DEFAULT_CSS = """
    StartupSplash { content-align: center middle; height: auto; padding: 2 0; color: $accent; }
    """
    def __init__(self, *, model_label: str, tier: str, live: bool) -> None:
        mode = "✳ LIVE" if live else "⚠ DEMO 演示"
        self._text = (
            _LOGO
            # ASCII art 是块字符,不含可检索的字面 "ARGOS" —— 补一行字面 wordmark,
            # 既让 renderable_text 含 "ARGOS"(测试断言/可访问性文本),又作品牌行。
            + "\n                   ARGOS\n"
            + f"\n     诚实可靠的终端编码智能体 · v{_VERSION}\n\n"
            + f"     模型 {model_label}({tier})   ·   {mode}\n"
            + "     输入目标开始,或输入 / 看命令  ·  ^C 退出"
        )
        super().__init__(self._text)

    @property
    def renderable_text(self) -> str:
        return self._text
