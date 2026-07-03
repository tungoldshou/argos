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
    override = os.environ.get("ARGOS_EVAL_CORPUS_DIR")
    if override:
        return Path(override).expanduser()
    from argos import config
    return Path(config.get("ARGOS_CONFIG_DIR") or (Path.home() / ".argos")).expanduser() / "eval" / "corpus"


def corpus_version(*, root: Path | None = None) -> int:
    p = (root or _corpus_root()) / "corpus.json"
    if not p.exists():
        return 0
    try:
        data = json.loads(p.read_text("utf-8"))
    except (json.JSONDecodeError, OSError):
        return 0
    return int(data.get("version", 1))


def list_tasks(*, root: Path | None = None) -> list[EvalTask]:
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
