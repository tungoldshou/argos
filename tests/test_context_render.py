"""#12 Context 可视化:T4 render.py 文本表格 + JSON(契约 §12;spec §7)。

7 测试覆盖对齐 + method 后缀 + 颜色 markup + JSON 字段序 + 不可序列化兜底。"""
from __future__ import annotations

import json

from argos.context.analyzer import ContextBreakdown, ContextBucket
from argos.context.render import format_json, format_table


def _b(system=100, memory=50, tools=80, messages=200, total=430, window=1000):
    return ContextBreakdown(
        ContextBucket("system", system, 1, "core/loop.py:471", "estimate:chars4"),
        ContextBucket("memory", memory, 4, "memory/auto.py:82", "estimate:chars4",
                       details=(("user", 0), ("project", 30), ("skill", 10), ("session", 10))),
        ContextBucket("tools", tools, 22, "core/loop.py:430", "estimate:chars4"),
        ContextBucket("messages", messages, 5, "memory/store.py:259", "api"),
        total=total, window=window, pct=total / window, method="api+estimate")


def test_format_table_contains_all_buckets():
    """5 个段名(system / memory / tools / messages / total)都在输出。"""
    out = format_table(_b())
    assert "system" in out
    assert "memory" in out
    assert "tools" in out
    assert "messages" in out
    assert "total" in out


def test_format_table_method_suffix_per_bucket():
    """每桶数字带 [est] 或 [api] 后缀(spec §12.1 锁)。"""
    out = format_table(_b())
    # system/tools/memory 估:[est]
    assert "[est]" in out
    # messages API:[api]
    assert "[api]" in out


def test_format_table_memory_details_expanded():
    """memory 段展开 4 个 sub(user / project / skill / session)。"""
    out = format_table(_b())
    assert "user" in out
    assert "project" in out
    assert "skill" in out
    assert "session" in out


def test_format_table_health_color_yellow():
    """pct=0.43 → green;pct=0.6 → yellow;pct=0.9 → red。"""
    out_g = format_table(_b(total=430, window=1000))  # 0.43
    assert "[green]" in out_g
    out_y = format_table(_b(total=600, window=1000))  # 0.6
    assert "[yellow]" in out_y
    out_r = format_table(_b(total=900, window=1000))  # 0.9
    assert "[red]" in out_r


def test_format_table_no_ansi_codes():
    """输出不含 ANSI 转义(只走 Textual markup,CLI 也能干净打印)。"""
    out = format_table(_b())
    assert "\x1b[" not in out
    assert "\033[" not in out


def test_format_json_keys_in_spec_order():
    """JSON 顶层键序 spec D13:system/memory/tools/messages/total/window/pct/health/method。"""
    out = format_json(_b())
    keys = list(json.loads(out).keys())
    assert keys == ["system", "memory", "tools", "messages", "total", "window", "pct", "health", "method"]


def test_format_json_serializable():
    """format_json 输出可被 json.loads 再 parse 回去(默认 default=str 兜底)。"""
    out = format_json(_b())
    parsed = json.loads(out)
    assert parsed["system"]["tokens"] == 100
    assert parsed["memory"]["entries"] == 4
    # memory details 是 list of [name, tokens](dataclass asdict 序列化为 list)
    assert parsed["memory"]["details"] == [["user", 0], ["project", 30], ["skill", 10], ["session", 10]]
    assert parsed["total"] == 430
    assert parsed["health"] == "green"
