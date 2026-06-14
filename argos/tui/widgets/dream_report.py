# argos/tui/widgets/dream_report.py
"""DreamReportCard:Dream 夜间整固的流内进度卡 + 报告子卡。

TUI v3 黑曜石之眼 spec §13。
纯展示组件(not a decision card):无按键绑定,无焦点争夺。

生命周期:
  1. 挂载后显示 echo 行 '› /dream' + 空阶段流
  2. 每次 DreamProgressEvent 到达 → append_stage(stage, detail)
  3. DreamReportEvent 到达 → show_report(report)
  4. 报告子卡(#dream-report-box)被 mount 后显示诚实计数

诚实铁律:
  - done 是唯一 $pass 绿色阶段;其余阶段 $eye 字形 + $ink 文字
  - 三计数颜色不可混用:promoted=$pass, rejected=$fail, skipped=$unverif
  - Row D 只在 promoted_name 字段被后端显式提供且 promoted>=1 时渲染(v1 省略)
  - markup=False 覆盖全部 plain-text Static;Rich Text 用 explicit span
  - DEFAULT_CSS 只用 $token 名,不含裸 hex

字形铁律(v3):◔ ◉ ❂ ◕ — 禁用 ◎◓◐◑●○▶ 等退役字形。
"""
from __future__ import annotations

from dataclasses import asdict
from typing import Any

from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Vertical
from textual.widgets import Static

# ── Rich Text 颜色常量(与 theme.py token 一一对应,Rich 不解析 $token) ───────
# DEFAULT_CSS 一律用 $token 名;Rich Text style 用 hex(Rich 不解析 $token)
_COL_PASS       = "#9ECE6A"  # $pass    : verdict passed — 唯一的绿
_COL_FAIL       = "#F7768E"  # $fail    : verdict failed — 唯一的红
_COL_UNVERIF    = "#FF9E64"  # $unverif : unverifiable / skipped — 橙
_COL_EYE        = "#D9A85C"  # $eye     : chrome 主强调 / 阶段字形
_COL_INK        = "#C8CCDA"  # $ink     : 散文正文
_COL_INK_DIM    = "#7E869C"  # $ink-dim : 次要信息
_COL_INK_FAINT  = "#525A73"  # $ink-faint: 键提示/caption
_COL_INK_BRIGHT = "#ECEEF5"  # $ink-bright: bold 标题

# ── 阶段→字形映射(铁律,不可改动)────────────────────────────────────────────
# spec §13:scan/memory → ◔;cluster/synthesize → ◉;promote → ❂;done → ◕
_STAGE_GLYPH: dict[str, str] = {
    "scan":       "◔",   # U+25D4 CIRCLE WITH UPPER RIGHT QUADRANT BLACK
    "cluster":    "◉",   # U+25C9 FISHEYE
    "synthesize": "◉",   # 同 cluster(backend emits this — render honestly)
    "promote":    "❂",   # U+2742 EIGHT TEARDROP-SPOKED ASTERISK
    "memory":     "◔",   # 同 scan
    "done":       "◕",   # U+25D5 CIRCLE WITH THREE QUARTERS BLACK
}

# 未知阶段兜底字形(不崩溃)
_FALLBACK_GLYPH = "·"


def _coerce_report(report: Any) -> dict[str, Any]:
    """将 DreamReport dataclass 或 dict 统一转为 dict。

    兼容两条入口:
      - DreamReportEvent 到达时 app.py 传入 dict
      - show_report 直接传 DreamReport dataclass
    """
    if isinstance(report, dict):
        return report
    # dataclass → dict(frozen=True,slots=True)
    try:
        return asdict(report)
    except Exception:
        # 兜底:尝试 __dict__ / vars
        try:
            return vars(report)
        except Exception:
            return {}


class DreamReportCard(Vertical):
    """Dream 夜间整固进度卡 + 报告子卡。

    挂载到 Transcript 流内(log.mount_block);纯只读展示,not focusable。
    app.py 三处挂钩:
      (1) _dream_cmd 202 → mount DreamReportCard()
      (2) DreamProgressEvent → card.append_stage(ev.stage, ev.detail)
      (3) DreamReportEvent  → card.show_report(ev)
    """

    DEFAULT_CSS = """
    DreamReportCard {
        height: auto;
        margin: 0 0 1 0;
        padding: 1 2;
        background: $stream;
        border: round $hairline-lit;
    }
    DreamReportCard #dream-stages {
        height: auto;
    }
    DreamReportCard #dream-report-box {
        background: $raise;
        padding: 1 2;
        margin: 1 0 0 0;
        height: auto;
        border: round $hairline-lit;
    }
    DreamReportCard .dream-echo {
        color: $ink-dim;
    }
    DreamReportCard .dream-caption {
        color: $ink-faint;
        margin: 1 0 0 0;
    }
    DreamReportCard .dream-footer {
        color: $ink-faint;
    }
    DreamReportCard .dream-report-title {
        text-style: bold;
        color: $ink-bright;
    }
    DreamReportCard .dream-report-row {
        color: $ink;
    }
    DreamReportCard .dream-report-dim {
        color: $ink-dim;
        margin: 1 0 0 0;
    }
    """

    # 是否已触发 done 行(幂等门禁)
    _done_appended: bool = False

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._done_appended = False
        self._report_box_mounted = False

    # ── 布局 ─────────────────────────────────────────────────────────────────

    def compose(self) -> ComposeResult:
        """初始结构:echo 行 + 空阶段流容器 + caption + footer。

        报告子卡(#dream-report-box)在 show_report 时动态 mount。
        """
        yield Static("› /dream", markup=False, classes="dream-echo")
        yield Vertical(id="dream-stages")
        yield Static(
            "可执行内容逐字来自源材料 · 模型只写叙述",
            markup=False,
            classes="dream-caption",
        )
        yield Static(
            "失败安全降级 · 全建议需用户确认 · argos/learning/dream",
            markup=False,
            classes="dream-footer",
        )

    # ── 公开 API ──────────────────────────────────────────────────────────────

    def append_stage(self, stage: str, detail: str) -> None:
        """追加一个阶段行到 #dream-stages 流。

        幂等 done:done 阶段只渲染一次(重复调用静默忽略)。
        颜色规则:
          - done → glyph ◕ + text 均用 $pass(唯一绿)
          - 其余  → glyph $eye,text $ink
        """
        if stage == "done":
            if self._done_appended:
                return  # 幂等:绝不重复 done 行
            self._done_appended = True

        glyph = _STAGE_GLYPH.get(stage, _FALLBACK_GLYPH)
        row_text = self._build_stage_row(stage, glyph, detail)

        # 用 Rich Text 渲染,markup=False 语义由 Static 的 renderable=Text 保证
        stage_static = Static(row_text, markup=False)
        # call_after_refresh:避免在 compose 期间 mount 子节点引发竞态
        self.call_after_refresh(self._mount_stage_row, stage_static)

    def show_report(self, report: Any) -> None:
        """挂载/更新报告子卡(#dream-report-box)。

        report 可以是 DreamReport dataclass 或等价 dict。
        诚实铁律:counts 逐字来自 report;零也诚实渲染。
        """
        d = _coerce_report(report)
        self.call_after_refresh(self._mount_report_box, d)

    # ── Rich Text 构建(可被测试直接调用,无需 headless) ─────────────────────

    def _build_stage_row(self, stage: str, glyph: str, detail: str) -> Text:
        """构建单个阶段行 Rich Text。

        done → glyph + label 均 $pass;其余 → glyph $eye,text $ink。
        detail 存在时追加 ' · {detail}'($ink-dim)。
        markup=False 语义:Text 对象本身不含 markup,由 Static 原样渲染。
        """
        t = Text()
        if stage == "done":
            t.append(glyph, style=_COL_PASS)
            t.append(f" {stage}", style=_COL_PASS)
        else:
            t.append(glyph, style=_COL_EYE)
            t.append(f" {stage}", style=_COL_INK)
            # 阶段特定标签(spec 精确格式)
            label = _STAGE_LABEL.get(stage, "")
            if label:
                t.append(f"    {label}", style=_COL_INK)
        if detail:
            t.append(f" · {detail}", style=_COL_INK_DIM)
        return t

    def _build_row_b(self, report: Any) -> Text:
        """构建 Row B:整合单元计数行(三色铁律)。

        "整合单元 {units_total} · 晋升 {promoted} · 驳回 {rejected} · 跳过 {skipped}"
        颜色:
          promoted → $pass (#9ECE6A)
          rejected → $fail (#F7768E)
          skipped  → $unverif (#FF9E64)
        """
        d = _coerce_report(report)
        units   = d.get("units_total", 0)
        promoted = d.get("promoted", 0)
        rejected = d.get("rejected", 0)
        skipped  = d.get("skipped", 0)

        t = Text()
        t.append(f"整合单元 {units} · ", style=_COL_INK)
        t.append(f"晋升 {promoted}", style=_COL_PASS)
        t.append(" · ", style=_COL_INK)
        t.append(f"驳回 {rejected}", style=_COL_FAIL)
        t.append(" · ", style=_COL_INK)
        t.append(f"跳过 {skipped}", style=_COL_UNVERIF)
        return t

    # ── 内部 mount 帮助(call_after_refresh 回调) ─────────────────────────────

    def _mount_stage_row(self, stage_static: Static) -> None:
        """在 #dream-stages 容器追加阶段 Static。"""
        try:
            stages = self.query_one("#dream-stages", Vertical)
            stages.mount(stage_static)
        except Exception:  # noqa: BLE001 — headless 离群环境静默
            pass

    def _mount_report_box(self, d: dict[str, Any]) -> None:
        """挂载(或更新)报告子卡。幂等:已挂载时更新内容。"""
        memory_merged  = d.get("memory_merged", 0)
        memory_archived = d.get("memory_archived", 0)
        promoted = d.get("promoted", 0)
        promoted_name = d.get("promoted_name")  # 后端 v1 不提供 → None

        if not self._report_box_mounted:
            # 首次挂载:构建整个子卡
            box = Vertical(id="dream-report-box")

            row_a = Static("─ 报告", markup=False, classes="dream-report-title")
            row_b_text = self._build_row_b(d)
            row_b = Static(row_b_text, markup=False, classes="dream-report-row")
            row_c_text = f"记忆合并 {memory_merged} · 归档 {memory_archived}"
            row_c = Static(row_c_text, markup=False, classes="dream-report-row")

            children = [row_a, row_b, row_c]

            # Row D:只在后端提供 promoted_name 且 promoted>=1 时渲染(v1 安全策略)
            if promoted >= 1 and promoted_name:
                row_d_text = f"晋升:{promoted_name}(综合自已验证 run)"
                row_d = Static(row_d_text, markup=False, classes="dream-report-dim")
                children.append(row_d)

            # caption 和 footer 已在外层 compose;子卡只含计数内容
            try:
                # 将子卡 mount 在 caption 之前(保持视觉顺序)
                caption = self.query_one(".dream-caption", Static)
                self.mount(box, before=caption)
                # 同步 mount 子节点到 box
                for child in children:
                    box.mount(child)
                self._report_box_mounted = True
            except Exception:  # noqa: BLE001
                pass
        else:
            # 后续更新:重建子卡内容
            try:
                box = self.query_one("#dream-report-box", Vertical)
                box.remove_children()
                row_a = Static("─ 报告", markup=False, classes="dream-report-title")
                row_b_text = self._build_row_b(d)
                row_b = Static(row_b_text, markup=False, classes="dream-report-row")
                row_c_text = f"记忆合并 {memory_merged} · 归档 {memory_archived}"
                row_c = Static(row_c_text, markup=False, classes="dream-report-row")
                children = [row_a, row_b, row_c]
                if promoted >= 1 and promoted_name:
                    row_d_text = f"晋升:{promoted_name}(综合自已验证 run)"
                    row_d = Static(row_d_text, markup=False, classes="dream-report-dim")
                    children.append(row_d)
                for child in children:
                    box.mount(child)
            except Exception:  # noqa: BLE001
                pass


# ── 阶段标签(stage stream 里的人话补充,追加在阶段名后) ──────────────────────
# spec §13 exact format strings — only used when detail is absent
_STAGE_LABEL: dict[str, str] = {
    "scan":       "候选区",
    "cluster":    "",     # cluster 行从 detail 拿 '3 簇(Jaccard ≥ 0.35)'
    "synthesize": "",
    "promote":    "A/B 晋升门",
    "memory":     "记忆整理",
    "done":       "",
}
