"""Phase 5 slash:解析为 (name, arg) 并映射到动作枚举(spec §4.5)。"""
from __future__ import annotations

import pytest

from argos.tui.commands import SlashCommand, parse_slash, COMMAND_NAMES, COMMAND_HELP, match_commands


def test_known_commands_listed():
    assert set(COMMAND_NAMES) == {
        "yolo", "trust",  # trust = 信任拨盘(P4 阶段3);yolo = /trust l4 别名(保留)
        "undo", "clear", "retry", "status", "model", "resume", "cost",
        "help", "tools", "skills", "mcp", "plan", "hooks",
        "lsp",  # 2026-06-06:列出 / 重载 LSP 配置(/lsp, /lsp reload)
        "permissions",  # 2026-06-06:Smart approval — 列出 / 重载 permissions 配置(/permissions, /permissions reload)
        "verify", "security-review", "simplify",  # 2026-06-06:3 skill slash
        "runs",  # 2026-06-06:列出 / 控制 daemon run(/runs, /runs {id} resume|cancel)
        "eval",  # 2026-06-07:Agent 自我评估 + A/B(/eval, /eval run, /eval compare)
        "routing",  # 2026-06-07:per-task model routing 配置 + history(/routing, /routing set)
        "context",  # 2026-06-07:Context 可视化(/context, /context --json)
        "ledger",   # P3b §6:行为账本(/ledger — 列出当前 run 的人话条目 + 撤销状态)
        "orders",   # P5b §9:列出自治常驻指令(/orders)—conductor 自治面
        "confirm",  # P5b §9:确认 conductor 建议(/confirm <suggestion_id>)—自治面
        "dismiss",  # P5b §9:忽略 conductor 建议(/dismiss <suggestion_id>)
        "dream",    # T10:夜间整合 Dream(聚类综合+记忆整理;/dream status 看报告)
        "setup",    # 2026-06-21 #3:无 key 引导(/setup → 提示退出后运行 argos setup)
        "journal",  # 2026-06-21 #7:显示账本 JSONL 路径(/journal [run_id])—让可篡改账本可发现
        "loop", "goal", "schedule", "watch",  # Batch 2:循环/目标/定时/监视(parse 层,行为待接线)
    }


def test_capability_discovery_commands_known():
    """能力可见命令(/help /tools /skills /mcp)必须 known=True,才会进 _dispatch_slash 分发。"""
    for name in ("help", "tools", "skills", "mcp"):
        cmd = parse_slash(f"/{name}")
        assert cmd is not None and cmd.known is True, f"/{name} 应为已知命令"


def test_parse_plain_text_is_not_a_command():
    assert parse_slash("帮我修个 bug") is None


def test_parse_bare_command():
    cmd = parse_slash("/yolo")
    assert isinstance(cmd, SlashCommand)
    assert cmd.name == "yolo" and cmd.arg == ""


def test_parse_command_with_arg():
    cmd = parse_slash("/model premium")
    assert cmd.name == "model" and cmd.arg == "premium"


def test_parse_strips_whitespace():
    cmd = parse_slash("  /resume   2  ")
    assert cmd.name == "resume" and cmd.arg == "2"


def test_parse_unknown_command_returns_error_marker():
    cmd = parse_slash("/frobnicate")
    assert cmd is not None
    assert cmd.name == "frobnicate"
    assert cmd.known is False


def test_known_flag_true_for_valid():
    assert parse_slash("/cost").known is True


# ── Batch 2: /loop /goal /schedule /watch parse-layer registration ─────────

def test_new_loop_commands_in_command_help():
    """All 4 new commands appear in COMMAND_HELP with non-empty descriptions."""
    for name in ("loop", "goal", "schedule", "watch"):
        assert name in COMMAND_HELP, f"/{name} missing from COMMAND_HELP"
        assert COMMAND_HELP[name], f"/{name} has empty description"


def test_parse_goal_with_verify_pipe():
    """parse_slash parses /goal with pipe-style verify arg as known."""
    cmd = parse_slash("/goal fix bug | verify: pytest")
    assert cmd is not None
    assert cmd.name == "goal"
    assert cmd.arg == "fix bug | verify: pytest"
    assert cmd.known is True


def test_parse_loop_known():
    cmd = parse_slash("/loop run tests until: all pass")
    assert cmd is not None and cmd.known is True
    assert cmd.name == "loop"


def test_parse_schedule_known():
    cmd = parse_slash("/schedule 0 3 * * * dream")
    assert cmd is not None and cmd.known is True


def test_parse_watch_known():
    cmd = parse_slash("/watch src/**/*.py run tests")
    assert cmd is not None and cmd.known is True


def test_match_commands_schedule_prefix():
    """match_commands('/sch') includes 'schedule'."""
    names = [n for n, _ in match_commands("/sch")]
    assert "schedule" in names


def test_match_commands_watch_prefix():
    names = [n for n, _ in match_commands("/wat")]
    assert "watch" in names


def test_match_commands_loop_prefix():
    names = [n for n, _ in match_commands("/lo")]
    assert "loop" in names


def test_match_commands_goal_prefix():
    names = [n for n, _ in match_commands("/go")]
    assert "goal" in names
