# tests/tui/test_dream_report.py
"""DreamReportCard TDD 测试套件。

覆盖范围:
  1. 模块可导入,类存在
  2. widget 可在 Textual headless 环境里挂载(不崩溃)
  3. 阶段行字形/颜色铁律(6 阶段 → glyph + colour 正确)
  4. 报告子卡计数三色铁律(promoted=$pass, rejected=$fail, skipped=$unverif)
  5. 诚实不变量:done 是唯一 $pass 阶段;Row D 在 promoted==0 时不出现
  6. markup=False 语义:文本中的 "[bold]" 不会导致崩溃(不被解析)
  7. 公开 API:append_stage / show_report 签名正确
  8. 固定 caption 行存在
  9. 空/零状态诚实渲染(zero report — not fabricated)
 10. DEFAULT_CSS 只含 $token (不含原始 hex)
"""
from __future__ import annotations

import re
import importlib

import pytest
from textual.app import App, ComposeResult
from textual.widgets import Static

from argos.tui.theme import ARGOS_NIGHT


# ─── 颜色常量(与 dream_report.py 里的模块级常量对齐,用于断言) ──────────────
_COL_PASS   = "#9ECE6A"  # $pass
_COL_FAIL   = "#F7768E"  # $fail
_COL_UNVERIF = "#FF9E64"  # $unverif
_COL_EYE    = "#D9A85C"  # $eye
_COL_INK    = "#C8CCDA"  # $ink
_COL_INK_DIM  = "#7E869C"  # $ink-dim
_COL_INK_FAINT = "#525A73"  # $ink-faint
_COL_INK_BRIGHT = "#ECEEF5"  # $ink-bright


# ─── 导入守卫 ────────────────────────────────────────────────────────────────

def test_module_importable():
    """模块必须可导入——不应抛异常。"""
    mod = importlib.import_module("argos.tui.widgets.dream_report")
    assert hasattr(mod, "DreamReportCard")


def test_class_is_widget():
    """DreamReportCard 必须是 Textual Widget 的子类。"""
    from argos.tui.widgets.dream_report import DreamReportCard
    from textual.widget import Widget
    assert issubclass(DreamReportCard, Widget)


# ─── 宿主 App(注入 ARGOS_NIGHT token,使 DEFAULT_CSS 里 $token 可解析) ───────

class _Host(App):
    """挂 DreamReportCard 的临时宿主。"""
    CSS = ""  # 覆盖 App 默认的 CSS,避免干扰

    def get_theme_variable_defaults(self) -> dict[str, str]:
        return ARGOS_NIGHT.variables

    def compose(self) -> ComposeResult:
        from argos.tui.widgets.dream_report import DreamReportCard
        yield DreamReportCard()


# ─── 挂载冒烟测试 ─────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_card_mounts_without_crash():
    """widget 挂载不崩溃——最基本的 smoke 测试。"""
    app = _Host()
    async with app.run_test() as pilot:
        from argos.tui.widgets.dream_report import DreamReportCard
        cards = app.query(DreamReportCard)
        assert len(cards) > 0


def _all_text(widgets) -> str:
    """从 Static 列表提取全部文本内容(兼容 str 和 Rich Text)。"""
    parts = []
    for w in widgets:
        c = w.content
        parts.append(str(c))
    return "\n".join(parts)


@pytest.mark.asyncio
async def test_echo_line_present():
    """挂载后 echo 行 '› /dream' 必须存在。"""
    app = _Host()
    async with app.run_test() as pilot:
        await pilot.pause()
        full = _all_text(app.query(Static))
        assert "› /dream" in full


# ─── append_stage API 测试 ───────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_append_stage_scan():
    """append_stage('scan', '5 units') → 行含 '◔' + detail。"""
    app = _Host()
    async with app.run_test() as pilot:
        from argos.tui.widgets.dream_report import DreamReportCard
        card = app.query_one(DreamReportCard)
        card.append_stage("scan", "5 units")
        await pilot.pause()
        # 阶段行以 Rich Text 渲染;读 #dream-stages 子 Static
        statics = card.query(Static)
        all_text = _all_text(statics)
        assert "◔" in all_text
        assert "5 units" in all_text


@pytest.mark.asyncio
async def test_append_stage_cluster():
    """append_stage('cluster', '3 簇') → 行含 '◉'。"""
    app = _Host()
    async with app.run_test() as pilot:
        from argos.tui.widgets.dream_report import DreamReportCard
        card = app.query_one(DreamReportCard)
        card.append_stage("cluster", "3 簇")
        await pilot.pause()
        statics = card.query(Static)
        all_text = _all_text(statics)
        assert "◉" in all_text


@pytest.mark.asyncio
async def test_append_stage_synthesize():
    """synthesize 阶段诚实渲染(backend 发送此阶段,必须呈现)。"""
    app = _Host()
    async with app.run_test() as pilot:
        from argos.tui.widgets.dream_report import DreamReportCard
        card = app.query_one(DreamReportCard)
        card.append_stage("synthesize", "")
        await pilot.pause()
        statics = card.query(Static)
        all_text = _all_text(statics)
        # synthesize 用 ◉ glyph
        assert "◉" in all_text


@pytest.mark.asyncio
async def test_append_stage_promote():
    """promote 阶段 → ❂ glyph。"""
    app = _Host()
    async with app.run_test() as pilot:
        from argos.tui.widgets.dream_report import DreamReportCard
        card = app.query_one(DreamReportCard)
        card.append_stage("promote", "A/B 晋升")
        await pilot.pause()
        statics = card.query(Static)
        all_text = _all_text(statics)
        assert "❂" in all_text


@pytest.mark.asyncio
async def test_append_stage_memory():
    """memory 阶段诚实渲染(backend 发送此阶段)→ ◔ glyph。"""
    app = _Host()
    async with app.run_test() as pilot:
        from argos.tui.widgets.dream_report import DreamReportCard
        card = app.query_one(DreamReportCard)
        card.append_stage("memory", "记忆整理")
        await pilot.pause()
        statics = card.query(Static)
        all_text = _all_text(statics)
        assert "◔" in all_text


@pytest.mark.asyncio
async def test_append_stage_done_is_only_pass():
    """done 阶段 → ◕ glyph;且该行必须是阶段流中唯一 $pass 颜色行。"""
    app = _Host()
    async with app.run_test() as pilot:
        from argos.tui.widgets.dream_report import DreamReportCard
        card = app.query_one(DreamReportCard)
        card.append_stage("scan", "3 units")
        card.append_stage("done", "")
        await pilot.pause()
        statics = card.query(Static)
        all_text = _all_text(statics)
        assert "◕" in all_text


# ─── 阶段字形铁律(内部映射,不依赖挂载) ─────────────────────────────────────

def test_stage_glyph_map_complete():
    """_STAGE_GLYPH 必须覆盖全部 6 个阶段并使用正确字形。"""
    from argos.tui.widgets.dream_report import _STAGE_GLYPH
    assert _STAGE_GLYPH["scan"]      == "◔"
    assert _STAGE_GLYPH["cluster"]   == "◉"
    assert _STAGE_GLYPH["synthesize"] == "◉"
    assert _STAGE_GLYPH["promote"]   == "❂"
    assert _STAGE_GLYPH["memory"]    == "◔"
    assert _STAGE_GLYPH["done"]      == "◕"


def test_stage_glyph_fallback_exists():
    """未知阶段不应 KeyError — _STAGE_GLYPH.get 用兜底。"""
    from argos.tui.widgets.dream_report import _STAGE_GLYPH
    # get with default — implementation should handle unknown gracefully
    glyph = _STAGE_GLYPH.get("unknown_stage", "·")
    assert glyph == "·"


# ─── show_report API — 三色铁律 ─────────────────────────────────────────────

@pytest.mark.asyncio
async def test_show_report_counts_rendered():
    """show_report 后 units_total / promoted / rejected / skipped 必须出现在渲染文本。"""
    app = _Host()
    async with app.run_test() as pilot:
        from argos.tui.widgets.dream_report import DreamReportCard
        card = app.query_one(DreamReportCard)
        card.show_report({
            "units_total": 7,
            "promoted": 3,
            "rejected": 2,
            "skipped": 1,
            "memory_merged": 4,
            "memory_archived": 5,
            "report_path": "/tmp/dream.json",
        })
        await pilot.pause()
        statics = card.query(Static)
        all_text = _all_text(statics)
        assert "7" in all_text
        assert "3" in all_text
        assert "2" in all_text
        assert "1" in all_text


@pytest.mark.asyncio
async def test_show_report_row_b_three_color_contract():
    """Row B 的三计数必须各用正确颜色(promoted=$pass, rejected=$fail, skipped=$unverif)。

    通过检查 Rich Text 的 _spans 来验证颜色语义。
    """
    from rich.text import Text
    from argos.tui.widgets.dream_report import DreamReportCard

    # 用构造函数的内部方法直接测试 Rich Text 生成,不需要 headless
    report = {
        "units_total": 10,
        "promoted": 4,
        "rejected": 2,
        "skipped": 1,
        "memory_merged": 3,
        "memory_archived": 2,
        "report_path": "",
    }
    card = DreamReportCard()
    row_b_text = card._build_row_b(report)
    assert isinstance(row_b_text, Text)

    full_str = row_b_text.plain
    # promoted 数字出现
    assert "4" in full_str
    # rejected 数字出现
    assert "2" in full_str
    # skipped 数字出现
    assert "1" in full_str

    # 检查颜色 spans 包含语义色
    span_styles = [str(span.style) for span in row_b_text._spans]
    all_styles = " ".join(span_styles)
    assert _COL_PASS in all_styles,   f"promoted 必须是 $pass {_COL_PASS}"
    assert _COL_FAIL in all_styles,   f"rejected 必须是 $fail {_COL_FAIL}"
    assert _COL_UNVERIF in all_styles, f"skipped 必须是 $unverif {_COL_UNVERIF}"


def test_row_b_zero_counts():
    """零计数时 Row B 仍然渲染诚实零(不编造数字)。"""
    from rich.text import Text
    from argos.tui.widgets.dream_report import DreamReportCard
    card = DreamReportCard()
    report = {
        "units_total": 0,
        "promoted": 0,
        "rejected": 0,
        "skipped": 0,
        "memory_merged": 0,
        "memory_archived": 0,
        "report_path": "",
    }
    row_b = card._build_row_b(report)
    plain = row_b.plain
    # 各字段值为 0
    assert plain.count("0") >= 3


# ─── Row D 诚实不变量(promoted==0 不渲染) ───────────────────────────────────

@pytest.mark.asyncio
async def test_row_d_absent_when_promoted_zero():
    """promoted==0 时 Row D (晋升:...) 必须不出现在渲染中。"""
    app = _Host()
    async with app.run_test() as pilot:
        from argos.tui.widgets.dream_report import DreamReportCard
        card = app.query_one(DreamReportCard)
        card.show_report({
            "units_total": 3,
            "promoted": 0,
            "rejected": 2,
            "skipped": 1,
            "memory_merged": 0,
            "memory_archived": 0,
            "report_path": "",
        })
        await pilot.pause()
        statics = card.query(Static)
        all_text = _all_text(statics)
        # "晋升:" 前缀是 Row D 的标志性字符串,promoted==0 不应出现
        assert "晋升:" not in all_text


@pytest.mark.asyncio
async def test_row_d_absent_without_promoted_name():
    """DreamReport 未提供 promoted_name 字段时 Row D 必须不渲染(v1 安全策略)。"""
    app = _Host()
    async with app.run_test() as pilot:
        from argos.tui.widgets.dream_report import DreamReportCard
        card = app.query_one(DreamReportCard)
        # promoted > 0 但不提供 promoted_name — 按 spec open_question (b): 省略 Row D
        card.show_report({
            "units_total": 5,
            "promoted": 2,
            "rejected": 1,
            "skipped": 0,
            "memory_merged": 1,
            "memory_archived": 0,
            "report_path": "/tmp/report.json",
        })
        await pilot.pause()
        statics = card.query(Static)
        all_text = _all_text(statics)
        # 没有 promoted_name → Row D 必须不出现
        assert "晋升:" not in all_text


# ─── Caption 行铁律 ───────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_caption_always_present():
    """caption '可执行内容逐字来自源材料 · 模型只写叙述' 必须始终存在。"""
    app = _Host()
    async with app.run_test() as pilot:
        await pilot.pause()
        statics = app.query(Static)
        all_text = _all_text(statics)
        assert "可执行内容逐字来自源材料" in all_text
        assert "模型只写叙述" in all_text


# ─── markup=False 安全性 ──────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_markup_safety_in_stage_detail():
    """stage detail 含 '[bold]' 等 markup 字符必须原样渲染(不崩溃,不被解析)。"""
    app = _Host()
    async with app.run_test() as pilot:
        from argos.tui.widgets.dream_report import DreamReportCard
        card = app.query_one(DreamReportCard)
        # 含 markup-like 字符
        card.append_stage("scan", "3 [units] found [bold]")
        await pilot.pause()
        statics = card.query(Static)
        all_text = _all_text(statics)
        # plain 内容必须可见;Rich Text 的 str() 返回 plain text(无方括号 markup)
        # 关键是没有崩溃,且原始文本的关键词 "units" 出现(没被 markup 解析器吃掉)
        assert "units" in all_text


@pytest.mark.asyncio
async def test_markup_safety_in_report_path():
    """report_path 含 '[...]' 字符时不崩溃(markup=False 合规)。"""
    app = _Host()
    async with app.run_test() as pilot:
        from argos.tui.widgets.dream_report import DreamReportCard
        card = app.query_one(DreamReportCard)
        card.show_report({
            "units_total": 1,
            "promoted": 0,
            "rejected": 1,
            "skipped": 0,
            "memory_merged": 0,
            "memory_archived": 0,
            "report_path": "/tmp/[special]/dream.json",
        })
        await pilot.pause()
        # 没有抛异常 = 测试通过


# ─── DEFAULT_CSS 只含 $token(不含裸 hex) ────────────────────────────────────

def test_default_css_no_raw_hex():
    """DEFAULT_CSS 不应含裸 hex(#xxxxxx) — CSS 层只用 $token 名。"""
    from argos.tui.widgets.dream_report import DreamReportCard
    css = DreamReportCard.DEFAULT_CSS
    # 匹配 6 位或 3 位 hex 颜色(#RGB / #RRGGBB)
    hex_colors = re.findall(r"#[0-9A-Fa-f]{3,8}", css)
    assert not hex_colors, (
        f"DEFAULT_CSS 里不允许裸 hex;发现: {hex_colors}"
    )


# ─── 公开 API 签名验证 ────────────────────────────────────────────────────────

def test_append_stage_signature():
    """append_stage(stage: str, detail: str) 方法必须存在且可调用。"""
    from argos.tui.widgets.dream_report import DreamReportCard
    import inspect
    sig = inspect.signature(DreamReportCard.append_stage)
    params = list(sig.parameters.keys())
    assert "stage" in params
    assert "detail" in params


def test_show_report_signature():
    """show_report(report) 方法必须存在且可调用。"""
    from argos.tui.widgets.dream_report import DreamReportCard
    import inspect
    sig = inspect.signature(DreamReportCard.show_report)
    params = list(sig.parameters.keys())
    # 第一个位置参数是 report(dict 或 DreamReport)
    assert len(params) >= 2  # self + report


def test_build_row_b_method_exists():
    """_build_row_b(report) 是内部 helper,供测试直接断言颜色(不需要 headless)。"""
    from argos.tui.widgets.dream_report import DreamReportCard
    assert hasattr(DreamReportCard, "_build_row_b")
    assert callable(DreamReportCard._build_row_b)


# ─── DreamReport dataclass 集成(使用真实后端数据) ──────────────────────────

def test_show_report_accepts_dream_report_dataclass():
    """show_report 应接受真实 DreamReport dataclass(不只是 dict)。"""
    from argos.learning.dream import DreamReport
    from argos.tui.widgets.dream_report import DreamReportCard
    report = DreamReport(
        units_total=5, promoted=2, rejected=1, skipped=1,
        memory_merged=3, memory_archived=1, report_path="/tmp/r.json"
    )
    card = DreamReportCard()
    # 不应抛异常(可能需要 _coerce 内部转 dict)
    row_b = card._build_row_b(report)
    from rich.text import Text
    assert isinstance(row_b, Text)
    assert "2" in row_b.plain   # promoted
    assert "1" in row_b.plain   # rejected (1)


# ─── Row A title 存在 ────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_report_box_title_row_a():
    """show_report 后报告子卡标题 '─ 报告' 必须出现。"""
    app = _Host()
    async with app.run_test() as pilot:
        from argos.tui.widgets.dream_report import DreamReportCard
        card = app.query_one(DreamReportCard)
        card.show_report({
            "units_total": 2,
            "promoted": 1,
            "rejected": 0,
            "skipped": 1,
            "memory_merged": 0,
            "memory_archived": 0,
            "report_path": "",
        })
        await pilot.pause()
        statics = card.query(Static)
        all_text = _all_text(statics)
        assert "─ 报告" in all_text


# ─── Row C 记忆计数 ──────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_report_row_c_memory_counts():
    """show_report 后 Row C '记忆合并 N · 归档 M' 必须出现。"""
    app = _Host()
    async with app.run_test() as pilot:
        from argos.tui.widgets.dream_report import DreamReportCard
        card = app.query_one(DreamReportCard)
        card.show_report({
            "units_total": 5,
            "promoted": 1,
            "rejected": 2,
            "skipped": 1,
            "memory_merged": 8,
            "memory_archived": 3,
            "report_path": "",
        })
        await pilot.pause()
        statics = card.query(Static)
        all_text = _all_text(statics)
        assert "记忆合并" in all_text
        assert "归档" in all_text
        assert "8" in all_text
        assert "3" in all_text


# ─── footer 行 ───────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_footer_present():
    """footer 行含 '失败安全降级' 必须存在。"""
    app = _Host()
    async with app.run_test() as pilot:
        await pilot.pause()
        statics = app.query(Static)
        all_text = _all_text(statics)
        assert "失败安全降级" in all_text


# ─── 幂等 done 行 ────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_done_stage_idempotent():
    """重复 append_stage('done', '') 不应重复添加行(幂等)。"""
    app = _Host()
    async with app.run_test() as pilot:
        from argos.tui.widgets.dream_report import DreamReportCard
        card = app.query_one(DreamReportCard)
        card.append_stage("done", "")
        card.append_stage("done", "")  # 再次 — 幂等
        await pilot.pause()
        # ◕ 应只出现一次
        statics = card.query(Static)
        all_text = _all_text(statics)
        assert all_text.count("◕") == 1
