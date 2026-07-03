"""Internal documentation."""
from __future__ import annotations

import json

from argos.context.analyzer import ContextBreakdown, ContextBucket
from argos.context.render import format_json, format_table, format_table_plain, strip_markup


def _b(system=100, memory=50, tools=80, messages=200, total=430, window=1000):
    return ContextBreakdown(
        ContextBucket("system", system, 1, "core/loop.py:471", "estimate:chars4"),
        ContextBucket("memory", memory, 4, "memory/auto.py:82", "estimate:chars4",
                       details=(("user", 0), ("project", 30), ("skill", 10), ("session", 10))),
        ContextBucket("tools", tools, 22, "core/loop.py:430", "estimate:chars4"),
        ContextBucket("messages", messages, 5, "memory/store.py:259", "api"),
        total=total, window=window, pct=total / window, method="api+estimate")


def test_format_table_contains_all_buckets():
    """Internal documentation."""
    out = format_table(_b())
    assert "system" in out
    assert "memory" in out
    assert "tools" in out
    assert "messages" in out
    assert "total" in out


def test_format_table_method_suffix_per_bucket():
    """Internal documentation."""
    out = format_table(_b())
    assert "[est]" in out
    # messages API:[api]
    assert "[api]" in out


def test_format_table_memory_details_expanded():
    """Internal documentation."""
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
    """Internal documentation."""
    out = format_table(_b())
    assert "\x1b[" not in out
    assert "\033[" not in out


def test_format_json_keys_in_spec_order():
    """Internal documentation."""
    out = format_json(_b())
    keys = list(json.loads(out).keys())
    assert keys == ["system", "memory", "tools", "messages", "total", "window", "pct", "health", "method"]


def test_strip_markup_removes_tags():
    """Internal documentation."""
    assert strip_markup("[green]hello[/green]") == "hello"
    assert strip_markup("[bold red]text[/bold red]") == "text"
    assert strip_markup("no tags here") == "no tags here"
    assert strip_markup("[est]  100 tok  [est]") == "  100 tok  "


def test_format_table_plain_no_markup_tags():
    """Internal documentation."""
    out = format_table_plain(_b())
    assert "[green]" not in out
    assert "[/green]" not in out
    assert "[yellow]" not in out
    assert "[red]" not in out
    assert "[est]" not in out
    assert "[api]" not in out


def test_format_table_plain_still_contains_content():
    """Internal documentation."""
    out = format_table_plain(_b())
    assert "system" in out
    assert "memory" in out
    assert "tools" in out
    assert "messages" in out
    assert "total" in out
    assert "100" in out  # system token count


def test_format_table_markup_preserved_for_tui():
    """Internal documentation."""
    out = format_table(_b())
    assert "[green]" in out or "[yellow]" in out or "[red]" in out


def test_format_json_serializable():
    """Internal documentation."""
    out = format_json(_b())
    parsed = json.loads(out)
    assert parsed["system"]["tokens"] == 100
    assert parsed["memory"]["entries"] == 4
    assert parsed["memory"]["details"] == [["user", 0], ["project", 30], ["skill", 10], ["session", 10]]
    assert parsed["total"] == 430
    assert parsed["health"] == "green"
