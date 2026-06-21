"""eval/benchmarks / eval/runner / learning 用户可见串目录。

key 命名空间:eval.* / learn.*。

ZH 值与重构前的**原始中文串逐字一致**,确保 ARGOS_LANG=zh 下旧测试断言不破。
EN 值是面向英文漏斗用户的默认文案(README/品牌基调:calm, precise)。
"""
from __future__ import annotations

EN: dict[str, str] = {
    # ── terminal_bench.py CLI messages ──────────────────────────────────────
    "eval.tb.no_subset": (
        "[eval tb] No --subset specified; pass 'smoke' to run the built-in fixture,"
        " or pass comma-separated TB task directories."
    ),
    "eval.tb.path_not_found": "[eval tb] Path does not exist: {path}",
    # argparse help strings
    "eval.tb.cmd_help": "Run a Terminal-Bench subset (adapter; requires --subset)",
    "eval.tb.subset_help": "Comma-separated TB task directories; or 'smoke' to run the built-in fixture (default: smoke)",
    "eval.tb.keep_worktree_help": "Debug: keep worktree after run",
    "eval.tb.format_help": "Report format",
    "eval.tb.sync_output_help": "Wrap report block with DECSET 2026 (suitable for a real TTY; no-op on non-TTY)",
    "eval.tb.no_sync_output_help": "Explicitly disable sync output (for A/B comparison)",

    # ── terminal_bench_docker.py ─────────────────────────────────────────────
    "eval.docker.no_docker": "docker not found in PATH — TBContainerExecutor cannot start containers",
    "eval.docker.timeout": "[timeout] run-tests.sh exceeded {timeout}s without completing",
    "eval.docker.run_failed": "docker run failed: {exc_type}: {exc}",

    # ── terminal_bench_best_of_n.py ──────────────────────────────────────────
    "eval.bon.n_must_be_positive": "n must be ≥ 1, got {n}",

    # ── runner.py ───────────────────────────────────────────────────────────
    "eval.runner.loop_factory_required": "loop_factory_required: v1 uses fake stubs (real mode v1.1)",

    # ── dream.py ────────────────────────────────────────────────────────────
    "learn.dream.narrative_prompt": (
        "Below are multiple verified successful task experiences."
        " Please summarize in 2-4 sentences WHEN this applies and WHAT to watch out for."
        " Write text only — no code:\n"
    ),
    "learn.dream.synthesize_fallback": (
        "This skill is synthesized from {n} verified run(s) (goals below),"
        " applicable to similar tasks."
    ),
    "learn.dream.hinted_runner_prefix": "Reference the following verified experience:\n",

    # ── distiller.py ────────────────────────────────────────────────────────
    "learn.distiller.what_worked_intro": "This skill comes from a single verified run (replayable).",
    "learn.distiller.verify_footer": (
        "Exit code 0 = passed"
        " (skill promotion requires A/B pass rate strictly > baseline).\n"
    ),
}

ZH: dict[str, str] = {
    # ── terminal_bench.py CLI messages ──────────────────────────────────────
    "eval.tb.no_subset": (
        "[eval tb] 未指定 --subset;请传 'smoke' 跑内置 fixture,或逗号分隔 TB 任务目录。"
    ),
    "eval.tb.path_not_found": "[eval tb] 路径不存在:{path}",
    # argparse help strings
    "eval.tb.cmd_help": "跑 Terminal-Bench 子集(适配器,需 --subset)",
    "eval.tb.subset_help": "逗号分隔 TB 任务目录;或 'smoke' 跑内置 fixture(默认 smoke)",
    "eval.tb.keep_worktree_help": "调试:不删 worktree",
    "eval.tb.format_help": "报告格式",
    "eval.tb.sync_output_help": "报告块用 DECSET 2026 包住(适合真 TTY;非 TTY 自动 no-op)",
    "eval.tb.no_sync_output_help": "显式关同步输出(A/B 对比用)",

    # ── terminal_bench_docker.py ─────────────────────────────────────────────
    "eval.docker.no_docker": "docker 不在 PATH —— TBContainerExecutor 无法起容器",
    "eval.docker.timeout": "[超时] run-tests.sh 超过 {timeout}s 未完成",
    "eval.docker.run_failed": "docker run 失败:{exc_type}: {exc}",

    # ── terminal_bench_best_of_n.py ──────────────────────────────────────────
    "eval.bon.n_must_be_positive": "n 必须 ≥ 1,得 {n}",

    # ── runner.py ───────────────────────────────────────────────────────────
    "eval.runner.loop_factory_required": "loop_factory_required: v1 全用 fake 桩(真模式 v1.1)",

    # ── dream.py ────────────────────────────────────────────────────────────
    "learn.dream.narrative_prompt": (
        "以下是多次已验证成功的任务经验,请用 2-4 句中文总结"
        "「何时适用」与「注意事项」。只写文字,不要代码:\n"
    ),
    "learn.dream.synthesize_fallback": (
        "本技能综合自 {n} 次已验证通过的 run(目标见下),适用于同类任务。"
    ),
    "learn.dream.hinted_runner_prefix": "可参考以下已验证经验:\n",

    # ── distiller.py ────────────────────────────────────────────────────────
    "learn.distiller.what_worked_intro": "本技能来自一次通过 verify 的实际 run(可重放)。",
    "learn.distiller.verify_footer": (
        "退出码 0 = 通过(本技能晋升要求 A/B 实测通过率严格 > 基线)。\n"
    ),
}
