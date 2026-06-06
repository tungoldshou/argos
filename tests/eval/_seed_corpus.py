"""#7 T1 测试 fixture:14 个种子任务落盘到 tmp_path,供 corpus/loader/runner 测试复用。

不 git 跟踪(任务元数据可由维护者编辑 / 加新任务);每次 conftest 调用落 1 套新种子,
保证测试隔离。

14 任务:bug_fix 5 / refactor 3 / test_write 3 / doc 3(spec §4.3)。
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any


# 14 任务种子(每条:files dict + corpus.json entry)
SEED_TASKS: list[dict[str, Any]] = [
    {
        "id": "bug_fix_001_off_by_one",
        "category": "bug_fix",
        "difficulty": "easy",
        "title": "修复 off-by-one 错误(median 函数)",
        "files": {
            "goal.md": "修 memory/auto.py _score 函数对 last_used_at 未来的处理(应截 0 而非负)。\n请用 edit_file 工具。",
            "verify_cmd": "python3 -c \"import sys; sys.exit(0)\"\n",
            "category": "bug_fix\n",
            "difficulty": "easy\n",
        },
    },
    {
        "id": "bug_fix_002_path_join",
        "category": "bug_fix",
        "difficulty": "easy",
        "title": "修 daemon/worktree.py cleanup 对 temp fallback 路径的 race",
        "files": {
            "goal.md": "修 daemon/worktree.py cleanup 对 temp fallback 路径的 race。",
            "verify_cmd": "python3 -c \"import sys; sys.exit(0)\"\n",
            "category": "bug_fix\n",
            "difficulty": "easy\n",
        },
    },
    {
        "id": "bug_fix_003_missing_parent",
        "category": "bug_fix",
        "difficulty": "medium",
        "title": "修 cli/eval.py 跑 task 时 expected_files 不存在时崩",
        "files": {
            "goal.md": "修 cli/eval.py 跑 task 时 expected_files 不存在时崩。",
            "verify_cmd": "python3 -c \"import sys; sys.exit(0)\"\n",
            "category": "bug_fix\n",
            "difficulty": "medium\n",
        },
    },
    {
        "id": "bug_fix_004_off_by_one_loop",
        "category": "bug_fix",
        "difficulty": "medium",
        "title": "修 core/loop.py 步数累计 off-by-one(首步应记 1)",
        "files": {
            "goal.md": "修 core/loop.py 步数累计 off-by-one(首步应记 1)。",
            "verify_cmd": "python3 -c \"import sys; sys.exit(0)\"\n",
            "category": "bug_fix\n",
            "difficulty": "medium\n",
        },
    },
    {
        "id": "bug_fix_005_unverifiable_promote",
        "category": "bug_fix",
        "difficulty": "hard",
        "title": "修 verify_gate 把 unverifiable 误升为 passed 的边界",
        "files": {
            "goal.md": "修 verify_gate 把 unverifiable 误升为 passed 的边界。",
            "verify_cmd": "python3 -c \"import sys; sys.exit(0)\"\n",
            "category": "bug_fix\n",
            "difficulty": "hard\n",
        },
    },
    {
        "id": "refactor_001_extract_helper",
        "category": "refactor",
        "difficulty": "medium",
        "title": "抽 commands.py 中重复的 _cmd_or_unknown 逻辑",
        "files": {
            "goal.md": "抽 commands.py 中重复的 _cmd_or_unknown 逻辑。",
            "verify_cmd": "python3 -c \"import sys; sys.exit(0)\"\n",
            "category": "refactor\n",
            "difficulty": "medium\n",
        },
    },
    {
        "id": "refactor_002_dedup_repos",
        "category": "refactor",
        "difficulty": "medium",
        "title": "抽 daemon/server.py 重复的 _send_error 包裹",
        "files": {
            "goal.md": "抽 daemon/server.py 重复的 _send_error 包裹。",
            "verify_cmd": "python3 -c \"import sys; sys.exit(0)\"\n",
            "category": "refactor\n",
            "difficulty": "medium\n",
        },
    },
    {
        "id": "refactor_003_split_loop",
        "category": "refactor",
        "difficulty": "hard",
        "title": "拆 core/loop.py _drive (250 行) 为 3 个函数",
        "files": {
            "goal.md": "拆 core/loop.py _drive (250 行) 为 3 个函数。",
            "verify_cmd": "python3 -c \"import sys; sys.exit(0)\"\n",
            "category": "refactor\n",
            "difficulty": "hard\n",
        },
    },
    {
        "id": "test_write_001_verify_bounce",
        "category": "test_write",
        "difficulty": "easy",
        "title": "给 verify_gate.verify 写 tamper-detected 分支单测",
        "files": {
            "goal.md": "给 verify_gate.verify 写 tamper-detected 分支单测。",
            "verify_cmd": "python3 -c \"import sys; sys.exit(0)\"\n",
            "category": "test_write\n",
            "difficulty": "easy\n",
        },
    },
    {
        "id": "test_write_002_approval_levels",
        "category": "test_write",
        "difficulty": "easy",
        "title": "给 ApprovalGate 写 confirm 拒绝分支单测",
        "files": {
            "goal.md": "给 ApprovalGate 写 confirm 拒绝分支单测。",
            "verify_cmd": "python3 -c \"import sys; sys.exit(0)\"\n",
            "category": "test_write\n",
            "difficulty": "easy\n",
        },
    },
    {
        "id": "test_write_003_corpus_loader",
        "category": "test_write",
        "difficulty": "medium",
        "title": "给 eval/corpus.py load_corpus 写缺 goal.md 边界单测",
        "files": {
            "goal.md": "给 eval/corpus.py load_corpus 写缺 goal.md 边界单测。",
            "verify_cmd": "python3 -c \"import sys; sys.exit(0)\"\n",
            "category": "test_write\n",
            "difficulty": "medium\n",
        },
    },
    {
        "id": "doc_001_module_header",
        "category": "doc",
        "difficulty": "easy",
        "title": "给 memory/auto.py 顶补缺失的 §概要 行",
        "files": {
            "goal.md": "给 memory/auto.py 顶补缺失的 §概要 行。",
            "verify_cmd": "python3 -c \"import sys; sys.exit(0)\"\n",
            "category": "doc\n",
            "difficulty": "easy\n",
        },
    },
    {
        "id": "doc_002_architecture",
        "category": "doc",
        "difficulty": "medium",
        "title": "给 docs/eval.md 写一段'何时用 A/B'指南",
        "files": {
            "goal.md": "给 docs/eval.md 写一段'何时用 A/B'指南。",
            "verify_cmd": "python3 -c \"import sys; sys.exit(0)\"\n",
            "category": "doc\n",
            "difficulty": "medium\n",
        },
    },
    {
        "id": "doc_003_changelog_format",
        "category": "doc",
        "difficulty": "easy",
        "title": "给 CHANGELOG.md 写 0.2.0 模板段(虚构,验证格式)",
        "files": {
            "goal.md": "给 CHANGELOG.md 写 0.2.0 模板段(虚构,验证格式)。",
            "verify_cmd": "python3 -c \"import sys; sys.exit(0)\"\n",
            "category": "doc\n",
            "difficulty": "easy\n",
        },
    },
]


def write_seed_corpus(root: Path, *, version: int = 1) -> None:
    """把 14 任务写到 root/<id>/{goal.md,verify_cmd,category,difficulty},并写 corpus.json。"""
    root.mkdir(parents=True, exist_ok=True)
    for t in SEED_TASKS:
        d = root / t["id"]
        d.mkdir(exist_ok=True)
        for fname, content in t["files"].items():
            (d / fname).write_text(content, encoding="utf-8")
    manifest = {
        "version": version,
        "tasks": [
            {"id": t["id"], "category": t["category"], "difficulty": t["difficulty"],
             "title": t["title"], "estimated_minutes": 5}
            for t in SEED_TASKS
        ],
    }
    (root / "corpus.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
