"""文件 diff 块:仅左缘竖线 + 红绿 diff 高亮(spec §4.5,TUI v3 黑曜石之眼)。

v3 变更:
- border: round $panel → border-left: tall $hairline-lit(仅左缘一线)
- background: $raise(浮起面,比流面亮一档)
- border_title: 去掉 ⏺ 前缀,改纯文字 "Edit · {path}"
- border_subtitle: 减号改 U+2212(−,真数学减号,非 ASCII 连字符)

颜色铁律(design-audit 2026-06-14):
- 不使用第三方 theme(monokai)的 hex 色;diff 着色一律走项目 token:
  + 行: $pass   #9ECE6A(唯一的绿)
  − 行: $fail   #F7768E(唯一的红)
  @@ 行: $ink-dim #7E869C
  其余上下文行: $ink  #C8CCDA
"""
from __future__ import annotations

from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Vertical
from textual.widgets import Static

# 颜色 token 对应的 hex 常量(单一来源:theme.py ARGOS_NIGHT.variables)
# 修改颜色时同步更新 theme.py,不得在此独立硬编码无关 hex。
_PASS  = "#9ECE6A"   # $pass  — 唯一的绿,added 行
_FAIL  = "#F7768E"   # $fail  — 唯一的红,removed 行
_DIM   = "#7E869C"   # $ink-dim — 次要元信息,@@ hunk header
_INK   = "#C8CCDA"   # $ink   — 散文正文,context 行


def _render_diff(unified: str) -> Text:
    """将 unified diff 字符串按 token 语义色逐行着色,返回 Rich Text。

    着色规则(只识别行首字符,不依赖第三方 lexer):
      '+' → $pass (#9ECE6A)   — added
      '-' → $fail (#F7768E)   — removed
      '@' → $ink-dim          — hunk header
      其余 → $ink              — context / 文件头
    """
    out = Text(no_wrap=False, overflow="fold")
    for i, raw_line in enumerate(unified.splitlines(keepends=False)):
        if i > 0:
            out.append("\n")
        first = raw_line[:1]
        if first == "+":
            out.append(raw_line, style=_PASS)
        elif first == "-":
            out.append(raw_line, style=_FAIL)
        elif first == "@":
            out.append(raw_line, style=_DIM)
        else:
            out.append(raw_line, style=_INK)
    return out


class DiffView(Vertical):
    """文件变更 diff 块,左缘点亮发丝竖线,背景浮起。"""

    DEFAULT_CSS = """
    DiffView {
        border-left: tall $hairline-lit;
        border-title-color: $ink-bright;
        background: $raise;
        padding: 0 1;
        margin: 0 0 1 0;
        height: auto;
    }
    """

    def __init__(self, *, path: str, added: int, removed: int, unified: str) -> None:
        super().__init__()
        # 保留公开属性(API 兼容:wiring/外部读 d.path/d.added/d.removed/d.unified)
        self.path = path
        self.added = added
        self.removed = removed
        self.unified = unified
        self._unified = unified
        # v3: 纯文字标题,去掉 ⏺ 前缀;减号用 U+2212 而非 ASCII '-'
        self.border_title = f"Edit · {path}"
        self.border_subtitle = f"+{added} −{removed}"

    def compose(self) -> ComposeResult:
        yield Static(_render_diff(self._unified), id="diff")
