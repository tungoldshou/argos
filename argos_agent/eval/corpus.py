"""#7 T1 corpus schema + 任务解析。

读 `~/.argos/eval/corpus/<task_id>/{goal.md,verify_cmd,category,difficulty,...}` 落盘结构,
返 `EvalTask` dataclass(供 runner / CLI / TUI 用)。

- 路径:缺省 = `~/.argos/eval/corpus/`,可被 `ARGOS_EVAL_CORPUS_DIR` 覆盖(测试用)
- 缺文件 → raise FileNotFoundError(spec §10)
- 14 种子由 `tests/eval/_seed_corpus.py` 在 conftest 按需落(不 git 跟踪)

D1:corpus 人工维护(LLM 不生任务,防"我测我多聪明"循环)
D2:JSONL 走结果;corpus 用 manifest.json + 文件系统(spec §4.1)
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

Category = Literal["bug_fix", "refactor", "test_write", "doc", "self_check"]
Difficulty = Literal["easy", "medium", "hard"]


@dataclass(frozen=True, slots=True)
class EvalTask:
    """单个 eval 任务(spec §5.1)。

    字段:
      id / category / difficulty / title:corpus 标识
      goal:LLM 拿这一段当 user message
      verify_cmd:单行 shell 命令,退出码 0 = pass(spec §4.1)
      setup_cmd:可选(准备环境,exit 非 0 → setup_failed)
      expected_files:可选(glob 列表,任务完成后应出现的文件)
      working_dir:实际跑的工作目录(默认 = task_dir)
      corpus_version:corpus.json 的 version 字段
    """
    id: str
    category: str
    difficulty: str
    title: str
    goal: str
    verify_cmd: str
    setup_cmd: str | None
    expected_files: tuple[str, ...]
    working_dir: Path
    corpus_version: int


def _corpus_root() -> Path:
    """corpus 根目录:env var 优先(测试用),否则 ~/.argos/eval/corpus/。"""
    override = os.environ.get("ARGOS_EVAL_CORPUS_DIR")
    return Path(override) if override else (Path.home() / ".argos" / "eval" / "corpus")


def corpus_version(*, root: Path | None = None) -> int:
    """读 corpus.json 的 version 字段;文件不存在返 0(诚实空态)。"""
    p = (root or _corpus_root()) / "corpus.json"
    if not p.exists():
        return 0
    try:
        data = json.loads(p.read_text("utf-8"))
    except (json.JSONDecodeError, OSError):
        return 0
    return int(data.get("version", 1))


def list_tasks(*, root: Path | None = None) -> list[EvalTask]:
    """读 corpus.json + 各 <id>/ 目录,返 EvalTask 列表(按 id 升序)。

    缺目录的条目静默跳过(测试 fixture 不全时不爆)。
    """
    base = root or _corpus_root()
    manifest_p = base / "corpus.json"
    if not manifest_p.exists():
        return []
    try:
        data = json.loads(manifest_p.read_text("utf-8"))
    except (json.JSONDecodeError, OSError):
        return []
    version = int(data.get("version", 1))
    out: list[EvalTask] = []
    for t in data.get("tasks", []):
        title = t.get("title") or t["id"]
        task = _load_one(t["id"], base=base, version=version, title=title)
        if task is not None:
            out.append(task)
    out.sort(key=lambda x: x.id)
    return out


def load_task(task_id: str, *, root: Path | None = None) -> EvalTask:
    """按 id 加载单个 task;目录或 goal.md 缺失 → raise FileNotFoundError(spec §10)。"""
    base = root or _corpus_root()
    version = corpus_version(root=base)
    manifest_p = base / "corpus.json"
    title = task_id
    if manifest_p.is_file():
        try:
            data = json.loads(manifest_p.read_text("utf-8"))
            for t in data.get("tasks", []):
                if t.get("id") == task_id:
                    title = t.get("title") or task_id
                    break
        except (json.JSONDecodeError, OSError):
            pass
    task = _load_one(task_id, base=base, version=version, title=title)
    if task is None:
        raise FileNotFoundError(f"corpus task dir not found: {base / task_id}")
    return task


def _load_one(task_id: str, *, base: Path, version: int, title: str | None = None) -> EvalTask | None:
    """读 <base>/<task_id>/ 内的所有文件。任一必需文件缺失 → 返 None(供 list_tasks 跳过)。"""
    d = base / task_id
    if not d.is_dir():
        return None
    goal_p = d / "goal.md"
    verify_p = d / "verify_cmd"
    if not (goal_p.is_file() and verify_p.is_file()):
        return None
    try:
        goal = goal_p.read_text("utf-8").strip()
        verify_cmd = verify_p.read_text("utf-8").strip()
    except OSError:
        return None
    if not goal or not verify_cmd:
        return None
    setup_p = d / "setup.sh"
    setup_cmd: str | None = None
    if setup_p.is_file():
        try:
            setup_cmd = setup_p.read_text("utf-8").strip() or None
        except OSError:
            setup_cmd = None
    cat = "bug_fix"
    cat_p = d / "category"
    if cat_p.is_file():
        try:
            cat = cat_p.read_text("utf-8").strip() or "bug_fix"
        except OSError:
            pass
    diff = "medium"
    diff_p = d / "difficulty"
    if diff_p.is_file():
        try:
            diff = diff_p.read_text("utf-8").strip() or "medium"
        except OSError:
            pass
    final_title = title or task_id
    notes_p = d / "notes.md"
    if notes_p.is_file():
        try:
            first = notes_p.read_text("utf-8").splitlines()
            if first:
                final_title = first[0].lstrip("# ").strip() or (title or task_id)
        except OSError:
            pass
    exp_p = d / "expected_files"
    expected: tuple[str, ...] = ()
    if exp_p.is_file():
        try:
            expected = tuple(
                line.strip() for line in exp_p.read_text("utf-8").splitlines() if line.strip()
            )
        except OSError:
            expected = ()
    return EvalTask(
        id=task_id, category=cat, difficulty=diff, title=final_title, goal=goal,
        verify_cmd=verify_cmd, setup_cmd=setup_cmd, expected_files=expected,
        working_dir=d, corpus_version=version,
    )
