"""#7 T1 corpus schema + 任务解析测试。"""
from __future__ import annotations

import pytest

from argos.eval.corpus import corpus_version, list_tasks, load_task

from tests.eval._seed_corpus import write_seed_corpus


@pytest.fixture
def seed_corpus(tmp_path, monkeypatch):
    """落 14 个种子任务到 tmp_path/corpus,设 ARGOS_EVAL_CORPUS_DIR 指过去。"""
    root = tmp_path / "corpus"
    write_seed_corpus(root)
    monkeypatch.setenv("ARGOS_EVAL_CORPUS_DIR", str(root))
    return root


# ── corpus_version ─────────────────────────────────────────────────────


def test_corpus_version_default_is_1(seed_corpus):
    assert corpus_version() == 1


def test_corpus_version_missing_file_returns_0(tmp_path, monkeypatch):
    monkeypatch.setenv("ARGOS_EVAL_CORPUS_DIR", str(tmp_path / "nope"))
    assert corpus_version() == 0


def test_corpus_version_corrupt_json_returns_0(tmp_path, monkeypatch):
    p = tmp_path / "bad"
    p.mkdir()
    (p / "corpus.json").write_text("{not json", encoding="utf-8")
    monkeypatch.setenv("ARGOS_EVAL_CORPUS_DIR", str(p))
    assert corpus_version() == 0


# ── list_tasks ─────────────────────────────────────────────────────────


def test_list_tasks_returns_all_14_seeds(seed_corpus):
    tasks = list_tasks()
    assert len(tasks) == 14
    # 按 id 升序
    ids = [t.id for t in tasks]
    assert ids == sorted(ids)


def test_list_tasks_categories_distribution(seed_corpus):
    tasks = list_tasks()
    by_cat: dict[str, int] = {}
    for t in tasks:
        by_cat[t.category] = by_cat.get(t.category, 0) + 1
    assert by_cat == {"bug_fix": 5, "refactor": 3, "test_write": 3, "doc": 3}


def test_list_tasks_missing_corpus_json_returns_empty(tmp_path, monkeypatch):
    p = tmp_path / "nope"
    p.mkdir()
    monkeypatch.setenv("ARGOS_EVAL_CORPUS_DIR", str(p))
    assert list_tasks() == []


def test_list_tasks_skips_entries_with_missing_dir(seed_corpus):
    # 删一个 task 目录的内容 → list_tasks 跳过该条目
    import shutil
    shutil.rmtree(seed_corpus / "bug_fix_001_off_by_one")
    tasks = list_tasks()
    assert len(tasks) == 13
    assert all(t.id != "bug_fix_001_off_by_one" for t in tasks)


# ── load_task ──────────────────────────────────────────────────────────


def test_load_task_happy_path(seed_corpus):
    t = load_task("bug_fix_001_off_by_one")
    assert t.id == "bug_fix_001_off_by_one"
    assert t.category == "bug_fix"
    assert t.difficulty == "easy"
    assert "off-by-one" in t.title
    assert "_score" in t.goal
    assert t.verify_cmd == "python3 -c \"import sys; sys.exit(0)\""
    assert t.setup_cmd is None
    assert t.expected_files == ()
    assert t.corpus_version == 1
    assert t.working_dir == seed_corpus / "bug_fix_001_off_by_one"


def test_load_task_missing_dir_raises(seed_corpus):
    with pytest.raises(FileNotFoundError, match="corpus task dir not found"):
        load_task("nonexistent_task_999")


def test_load_task_missing_goal_md_raises(tmp_path, monkeypatch):
    p = tmp_path / "corpus"
    p.mkdir()
    (p / "corpus.json").write_text('{"version": 1, "tasks": [{"id": "x"}]}', encoding="utf-8")
    (p / "x").mkdir()
    (p / "x" / "verify_cmd").write_text("true", encoding="utf-8")
    monkeypatch.setenv("ARGOS_EVAL_CORPUS_DIR", str(p))
    with pytest.raises(FileNotFoundError, match="corpus task dir not found"):
        load_task("x")


def test_load_task_with_setup_sh(tmp_path, monkeypatch):
    """task 含 setup.sh → setup_cmd 字段被填。"""
    from tests.eval._seed_corpus import write_seed_corpus
    p = tmp_path / "corpus"
    # 在 seed 之上额外加一个含 setup.sh 的 task
    write_seed_corpus(p)
    extra = p / "task_with_setup"
    extra.mkdir()
    (extra / "goal.md").write_text("do it", encoding="utf-8")
    (extra / "verify_cmd").write_text("true", encoding="utf-8")
    (extra / "setup.sh").write_text("#!/bin/bash\necho ok\n", encoding="utf-8")
    (extra / "category").write_text("bug_fix", encoding="utf-8")
    (extra / "difficulty").write_text("easy", encoding="utf-8")
    # 加到 manifest
    import json
    manifest = json.loads((p / "corpus.json").read_text("utf-8"))
    manifest["tasks"].append({"id": "task_with_setup", "category": "bug_fix", "difficulty": "easy", "title": "x"})
    (p / "corpus.json").write_text(json.dumps(manifest), encoding="utf-8")
    monkeypatch.setenv("ARGOS_EVAL_CORPUS_DIR", str(p))
    t = load_task("task_with_setup")
    assert t.setup_cmd is not None
    assert "echo ok" in t.setup_cmd


def test_load_task_with_expected_files(tmp_path, monkeypatch):
    p = tmp_path / "corpus"
    from tests.eval._seed_corpus import write_seed_corpus
    write_seed_corpus(p)
    extra = p / "task_with_files"
    extra.mkdir()
    (extra / "goal.md").write_text("do it", encoding="utf-8")
    (extra / "verify_cmd").write_text("true", encoding="utf-8")
    (extra / "expected_files").write_text("a.py\nb.py\n", encoding="utf-8")
    import json
    manifest = json.loads((p / "corpus.json").read_text("utf-8"))
    manifest["tasks"].append({"id": "task_with_files", "category": "bug_fix", "difficulty": "easy", "title": "x"})
    (p / "corpus.json").write_text(json.dumps(manifest), encoding="utf-8")
    monkeypatch.setenv("ARGOS_EVAL_CORPUS_DIR", str(p))
    t = load_task("task_with_files")
    assert t.expected_files == ("a.py", "b.py")


def test_load_task_notes_md_first_line_becomes_title(tmp_path, monkeypatch):
    p = tmp_path / "corpus"
    from tests.eval._seed_corpus import write_seed_corpus
    write_seed_corpus(p)
    extra = p / "t_notes"
    extra.mkdir()
    (extra / "goal.md").write_text("g", encoding="utf-8")
    (extra / "verify_cmd").write_text("true", encoding="utf-8")
    (extra / "notes.md").write_text("# 修复 X\n一些细节", encoding="utf-8")
    import json
    manifest = json.loads((p / "corpus.json").read_text("utf-8"))
    manifest["tasks"].append({"id": "t_notes", "category": "bug_fix", "difficulty": "easy", "title": "placeholder"})
    (p / "corpus.json").write_text(json.dumps(manifest), encoding="utf-8")
    monkeypatch.setenv("ARGOS_EVAL_CORPUS_DIR", str(p))
    t = load_task("t_notes")
    assert t.title == "修复 X"


def test_corpus_env_var_overrides_root(monkeypatch, tmp_path):
    """ARGOS_EVAL_CORPUS_DIR 覆盖 ~/.argos/eval/corpus/。"""
    other = tmp_path / "other"
    write_seed_corpus(other, version=3)
    monkeypatch.setenv("ARGOS_EVAL_CORPUS_DIR", str(other))
    assert corpus_version() == 3
    assert len(list_tasks()) == 14
