"""LedgerTable:行为账本表格（TUI v3 · 黑曜石之眼 spec §14）。

纯展示组件 — display-only Static 子类,无焦点/无键处理/无决策流。
挂入 Transcript 流内（Transcript.mount_block 或 log.append_line 的 widget 变体）。

渲染结构（逐行严格按 spec §14 / .dc.html §14 原文）:
  1. Header:「行为账本 · run {run_id} · {N} 条」
  2. 列头行:「seq  动作 · 人话  风险  可逆  撤销」
  3. 发丝分隔线:「─」重复至宽度
  4. 数据行（每条 LedgerEntry 一行,5 列）
     - action=='undo_done' 的 sentinel 行过滤不渲染
  5. （footer 由调用方 handler 另外 append_line，不在 widget 内）

颜色铁律（spec §14 诚实规则）:
  - risk:    low→$ink-dim,  medium→$unverif(橙),  high→$fail(红)
  - display: "medium"→"med"（仅 display 映射,内部逻辑保持 canonical 值）
  - reversible: yes→$pass-weak(弱绿,E4防火墙),  no→$fail,  unknown→$unverif
  - undo_state: available→$pass(强绿),  done→$ink-dim,  impossible→$ink-faint
  - 未知值 → $ink-faint + 原样显示（兜底诚实）

v3 字形铁律:
  ─  U+2500 发丝分隔线（列头下）
  禁止: ●○◎◐◑◇◆▶•（见全 TUI 字形禁令）

CSS 铁律:
  DEFAULT_CSS 一律用 $token 名;Rich Text style 用模块级 hex 常量（Rich 不解析 $token）。
  所有 hex 常量以注释标注对应 token 名，与 theme.py 保持同步。

中文注释/docstring 遵循 house norm。
"""
from __future__ import annotations

from rich.text import Text
from textual.widgets import Static

from argos.ledger.entry import LedgerEntry

# ── Rich Text 颜色常量（对应 ARGOS_NIGHT token，用于 Rich Text 渲染）──────────
# DEFAULT_CSS 一律用 $token 名；Rich Text style 用 hex（Rich 不解析 $token）。
# 每个常量注释标注对应 token 名，与 argos/tui/theme.py 同步。
_COL_EYE        = "#D9A85C"   # $eye:       金系主强调 / header 标题
_COL_INK_BRIGHT = "#ECEEF5"   # $ink-bright: bold 强调
_COL_INK        = "#C8CCDA"   # $ink:        正文散文层（summary_human）
_COL_INK_DIM    = "#7E869C"   # $ink-dim:    次要/非关键（seq / risk-low / undo-done）
_COL_INK_FAINT  = "#525A73"   # $ink-faint:  列头 / 占位 / undo-impossible
_COL_PASS       = "#9ECE6A"   # $pass:       verdict passed（undo_state=available）
_COL_PASS_WEAK  = "#73A857"   # $pass-weak:  弱通过 E4 防火墙（reversible=yes）
_COL_FAIL       = "#F7768E"   # $fail:       failed（risk=high / reversible=no）
_COL_UNVERIF    = "#FF9E64"   # $unverif:    不可知（risk=medium / reversible=unknown）
_COL_HAIRLINE   = "#23252E"   # $hairline:   发丝分隔线（几乎不可见）

# sentinel action 值：过滤不渲染
_SENTINEL_ACTION = "undo_done"

# 列宽（字符数）— 对应 spec .dc.html grid-template: 28px 1fr 56px 60px 80px
# TUI 使用 monospace，固定字符宽：
_W_SEQ   = 4    # seq 列（右填充）
_W_RISK  = 7    # 风险列（left-pad 后固定宽）
_W_REV   = 8    # 可逆列
_W_UNDO  = 11   # 撤销列
_COL_GAP = "  " # 列间两空格

# risk 显示映射（backend 存完整单词，display 映射 medium→med，spec §14 注释）
_RISK_DISPLAY = {
    "low":    "low",
    "medium": "med",   # spec §14: backend stores 'medium', display shows 'med'
    "high":   "high",
}

# risk → (display_text, hex_color)
_RISK_COLOR = {
    "low":    (_RISK_DISPLAY["low"],    _COL_INK_DIM),
    "medium": (_RISK_DISPLAY["medium"], _COL_UNVERIF),
    "high":   (_RISK_DISPLAY["high"],   _COL_FAIL),
}

# reversible → (display_text, hex_color)
_REV_COLOR = {
    "yes":     ("yes",     _COL_PASS_WEAK),  # E4 防火墙：弱绿，绝非强 $pass
    "no":      ("no",      _COL_FAIL),
    "unknown": ("unknown", _COL_UNVERIF),
}

# undo_state → (display_text, hex_color)
_UNDO_COLOR = {
    "available":  ("available",  _COL_PASS),       # 可操作 → 强绿
    "done":       ("done",       _COL_INK_DIM),    # 已完成 → 次要色
    "impossible": ("impossible", _COL_INK_FAINT),  # 不可逆 → 灰
}


class LedgerTable(Static):
    """行为账本表格——display-only，不可聚焦，不含任何决策逻辑。

    构造参数:
      entries  — list[LedgerEntry]，已由调用方过滤（或含 sentinel，构造器内再次过滤）。
      run_id   — str，当前 run 的 12 hex id，用于 header。

    公共 API（供 wiring 阶段 app.py 调用）:
      rendered_text     — property，返回纯文本内容（供测试断言 / 辅助用途）。
      _build_rich_text() — 返回 rich.text.Text，含完整 per-span 颜色（供测试颜色断言）。

    注意：_build_rich_text() 是纯计算（无 I/O、无 app 上下文依赖），
    可在构造阶段直接调用；Rich Text 对象作为初始内容传给 super().__init__()，
    避免在未挂载时调用 update()（update() 需要 Textual app 上下文）。
    """

    DEFAULT_CSS = """
    LedgerTable {
        height: auto;
        margin: 0 0 1 0;
        padding: 0 2;
        background: $stream;
    }
    """

    # display-only：不抢焦点
    can_focus = False

    def __init__(
        self,
        *,
        entries: list[LedgerEntry],
        run_id: str,
        **kwargs,
    ) -> None:
        # 过滤 sentinel（action=='undo_done'）行，不计入显示
        # 先于 super().__init__() 完成，供 _build_rich_text() 使用。
        self._entries: list[LedgerEntry] = [
            e for e in entries if e.action != _SENTINEL_ACTION
        ]
        self._run_id = run_id
        # _build_rich_text() 是纯计算，直接传给 super().__init__() 作初始内容。
        # markup=False 铁律：summary_human 可含 `[...]`，绝不当 Rich markup 解析。
        # 传 Rich Text 对象给 Static 避免 markup 解析；markup=False 保证 _render_markup=False。
        rich_content = self._build_rich_text()
        super().__init__(rich_content, markup=False, **kwargs)

    # ── 公共 API ────────────────────────────────────────────────────────────

    @property
    def rendered_text(self) -> str:
        """返回纯文本内容（供测试断言及调试）。"""
        return self._build_rich_text().plain

    def _build_rich_text(self) -> Text:
        """构建完整 Rich Text，含 per-span 颜色（诚实铁律在此落地）。

        此方法是颜色映射的单一真相源：
          - risk 颜色: low→$ink-dim, medium→$unverif, high→$fail
          - reversible 颜色: yes→$pass-weak, no→$fail, unknown→$unverif
          - undo_state 颜色: available→$pass, done→$ink-dim, impossible→$ink-faint
          - 发丝分隔线: ─ in $hairline
        """
        t = Text(no_wrap=False)
        entries = self._entries
        n = len(entries)

        # ── 1. Header line ──────────────────────────────────────────────
        # 「行为账本 · run {run_id} · {N} 条」in $ink
        t.append(f"行为账本 · run {self._run_id} · {n} 条", style=_COL_INK)
        t.append("\n")

        # ── 2. Column header row in $ink-faint ─────────────────────────
        # EXACT header cell texts per spec:
        # seq  动作 · 人话  风险  可逆  撤销
        seq_h   = "seq "    # 4 chars
        action_h = "动作 · 人话"
        risk_h   = "  风险 "     # right-padded
        rev_h    = "  可逆  "
        undo_h   = "  撤销"
        t.append(seq_h, style=_COL_INK_FAINT)
        t.append(action_h, style=_COL_INK_FAINT)
        t.append(risk_h, style=_COL_INK_FAINT)
        t.append(rev_h, style=_COL_INK_FAINT)
        t.append(undo_h, style=_COL_INK_FAINT)
        t.append("\n")

        # ── 3. Hairline separator ───────────────────────────────────────
        # 一行 ─ (U+2500)，60 宽即可（terminal 自动裁剪）
        t.append("─" * 60, style=_COL_HAIRLINE)
        t.append("\n")

        # ── 4. Data rows ────────────────────────────────────────────────
        for entry in entries:
            self._append_data_row(t, entry)

        return t

    def _append_data_row(self, t: Text, entry: LedgerEntry) -> None:
        """追加一条数据行到 Rich Text t。

        列顺序（spec §14 .dc.html grid-template-columns: 28px 1fr 56px 60px 80px）:
          [seq]  [summary_human]  [风险]  [可逆]  [撤销]
        列间双空格分隔。
        """
        # ── col 1: seq ──
        seq_str = str(entry.seq)
        # 右填充到 _W_SEQ 宽（seq 列固定宽）
        t.append(f"{seq_str:<{_W_SEQ}}", style=_COL_INK_FAINT)
        t.append(_COL_GAP)

        # ── col 2: summary_human（flex 列，原样输出）──
        # markup=False 保证：summary 中的 [test_foo] 等不被解析
        t.append(entry.summary_human, style=_COL_INK)
        t.append(_COL_GAP)

        # ── col 3: 风险 ──
        risk_val = entry.risk
        disp, color = _RISK_COLOR.get(risk_val, (risk_val, _COL_INK_DIM))
        t.append(f"{disp:<{_W_RISK}}", style=color)
        t.append(_COL_GAP)

        # ── col 4: 可逆 ──
        rev_val = entry.reversible
        disp_r, color_r = _REV_COLOR.get(rev_val, (rev_val, _COL_INK_FAINT))
        t.append(f"{disp_r:<{_W_REV}}", style=color_r)
        t.append(_COL_GAP)

        # ── col 5: 撤销 ──
        undo_val = entry.undo_state
        disp_u, color_u = _UNDO_COLOR.get(undo_val, ("—", _COL_INK_FAINT))
        t.append(f"{disp_u:<{_W_UNDO}}", style=color_u)

        t.append("\n")
