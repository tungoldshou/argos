"""#12 Context 可视化:文本表格 + JSON(契约 §12;spec §7)。

format_table / format_json 都是纯函数,无副作用。
颜色走 Textual markup([green]/[yellow]/[red]),非 ANSI;TUI 渲染直接用。
CLI(`argos context show`)走 format_table_plain:先剥 markup tag 再输出,
避免裸 `[green]…[/green]` 字面漏到终端。"""
from __future__ import annotations

import json
import re
from dataclasses import asdict
from typing import Any

from argos.context.analyzer import ContextBreakdown, ContextBucket


_HEALTH_COLOR = {"green": "green", "yellow": "yellow", "red": "red"}

# 匹配 Rich/Textual markup 标签:如 [green] / [/green] / [bold] / [/bold] 等
_MARKUP_RE = re.compile(r"\[/?[a-zA-Z][a-zA-Z0-9 _#]*\]")


def strip_markup(text: str) -> str:
    """剥去 Rich/Textual markup 标签,返回纯文本(用于 CLI 直接 print)。"""
    return _MARKUP_RE.sub("", text)


def _method_tag(method: str) -> str:
    """把 method 字段映射成 [est]/[api] 短标签(spec §12.1 锁透明)。"""
    if method.startswith("api"):
        return "[api]"
    return "[est]"


def _line(name: str, bucket: ContextBucket) -> str:
    """一桶一行:左 name 20 字符 + 右 token 7 字符 + method tag + source。"""
    tag = _method_tag(bucket.method)
    return f"  {name:<20}{bucket.tokens:>7,} tok  {tag:<8}{bucket.source}"


def _detail_line(name: str, tok: int) -> str:
    """memory 4 tier 子行(spec §7.1)。"""
    return f"    · {name:<16}{tok:>7,} tok  [est]"


def format_table(b: ContextBreakdown) -> str:
    """分桶文本表格(spec §7.1)。绿/黄/红对总行着色。"""
    color = _HEALTH_COLOR.get(b.health, "green")
    out: list[str] = []
    out.append("Argos Context Breakdown")
    out.append("─" * 50)
    out.append(_line("system", b.system))
    out.append(_line("memory (4 tier)", b.memory))
    for sub_name, sub_tok in b.memory.details:
        out.append(_detail_line(sub_name, sub_tok))
    out.append(_line(f"tools ({b.tools.entries})", b.tools))
    out.append(_line("messages", b.messages))
    out.append("─" * 50)
    out.append(
        f"[{color}]total {b.total:>7,} tok / {b.window:,} ({b.pct * 100:.1f}%)[/{color}]"
    )
    return "\n".join(out)


def _bucket_dict(b: ContextBucket) -> dict[str, Any]:
    """asdict 会把 tuple 变 tuple;details 转 list 保 JSON 友好。"""
    d = asdict(b)
    d["details"] = list(b.details)
    return d


def format_table_plain(b: ContextBreakdown) -> str:
    """纯文本版表格:同 format_table 结构,但已剥去 Rich/Textual markup 标签。
    供 CLI(`argos context show`)直接 print;TUI 继续用 format_table(含 markup)。"""
    return strip_markup(format_table(b))


def format_json(b: ContextBreakdown) -> str:
    """JSON 输出(spec §7.2 + D13 字段序:4 桶 → 汇总 → 顶层元信息)。"""
    d: dict[str, Any] = {
        "system": _bucket_dict(b.system),
        "memory": _bucket_dict(b.memory),
        "tools": _bucket_dict(b.tools),
        "messages": _bucket_dict(b.messages),
        "total": b.total,
        "window": b.window,
        "pct": b.pct,
        "health": b.health,
        "method": b.method,
    }
    return json.dumps(d, indent=2, ensure_ascii=False, default=str)
