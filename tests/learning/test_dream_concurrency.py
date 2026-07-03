"""Internal documentation."""
from __future__ import annotations

import asyncio
import os
from dataclasses import dataclass
from pathlib import Path

import pytest

from argos.learning import candidates as cand_mod
from argos.learning import dream
from argos.learning.candidates import save_candidate
from argos.learning.distiller import SkillCandidate
from argos.memory import consolidate as consol_mod

fcntl = pytest.importorskip("fcntl")



def _seed(root: Path, *, run: str, goal: str, ws: Path) -> Path:
    cand = SkillCandidate(
        name="learned",
        body_markdown=f"# {goal}\n\n```python\nprint('ok')\n```",
        verify_cmd="true",
        skill_md_path=Path("unused"),
    )
    p = save_candidate(cand, root=root, source_run=run, workspace=str(ws), goal=goal)
    assert p is not None
    return p


def _make_pipeline(tmp_path: Path) -> dream.DreamPipeline:
    class _Pass:
        def run(self, task, *, model_tier):
            @dataclass
            class _R:
                pass_status: str = "passed"
            return _R()

    class _Fail:
        def run(self, task, *, model_tier):
            @dataclass
            class _R:
                pass_status: str = "failed"
            return _R()

    return dream.DreamPipeline(
        candidates_root=tmp_path / "candidates",
        skills_root=tmp_path / "skills",
        memory_dir=tmp_path / "memory",
        dreams_dir=tmp_path / "dreams",
        runner_factory=lambda hint: (_Pass() if hint else _Fail()),
        broadcast_fn=None,
    )



def test_acquire_cross_process_lock_is_mutually_exclusive(tmp_path: Path):
    """Internal documentation."""
    cand_root = tmp_path / "candidates"

    fd1 = dream._acquire_cross_process_lock(cand_root)
    assert fd1 is not None and fd1 != dream._NO_FCNTL_FD, "首个应抢到真锁"

    fd2 = dream._acquire_cross_process_lock(cand_root)
    assert fd2 is None, "持锁期间第二个必须抢不到(返 None)"

    dream._release_cross_process_lock(fd1)
    fd3 = dream._acquire_cross_process_lock(cand_root)
    assert fd3 is not None and fd3 != dream._NO_FCNTL_FD, "释放后应可重抢"
    dream._release_cross_process_lock(fd3)


def test_lock_path_isolated_per_candidates_root(tmp_path: Path):
    """Internal documentation."""
    root_a = tmp_path / "a" / "candidates"
    root_b = tmp_path / "b" / "candidates"
    fd_a = dream._acquire_cross_process_lock(root_a)
    fd_b = dream._acquire_cross_process_lock(root_b)
    try:
        assert fd_a is not None and fd_a != dream._NO_FCNTL_FD
        assert fd_b is not None and fd_b != dream._NO_FCNTL_FD, (
            "不同 candidates_root 的锁应互不阻塞"
        )
        assert dream._lock_path_for(root_a) == root_a.parent / dream.DREAM_LOCK_NAME
    finally:
        dream._release_cross_process_lock(fd_a)
        dream._release_cross_process_lock(fd_b)



def test_run_skips_when_external_holder_owns_lock(tmp_path: Path):
    """Internal documentation."""
    cand_root = tmp_path / "candidates"
    ws = tmp_path / "ws"
    ws.mkdir()
    _seed(cand_root, run="ext00001aaaa", goal="fix login auth bug", ws=ws)

    external_fd = dream._acquire_cross_process_lock(cand_root)
    assert external_fd is not None and external_fd != dream._NO_FCNTL_FD

    pipe = _make_pipeline(tmp_path)
    try:
        report = asyncio.run(pipe.run())
        assert report is None, "外部持锁期间 run() 必须返 None(跨进程单飞)"
        from argos.learning.candidates import list_unconsumed
        assert len(list_unconsumed(cand_root)) == 1, "未跑就不该消费候选"
    finally:
        dream._release_cross_process_lock(external_fd)

    report2 = asyncio.run(pipe.run())
    assert report2 is not None, "外部锁释放后 run() 应能真跑"


def test_cross_process_busy_probe_reflects_external_holder(tmp_path: Path):
    """Internal documentation."""
    cand_root = tmp_path / "candidates"
    pipe = _make_pipeline(tmp_path)

    assert pipe.cross_process_busy() is False, "无外部持锁应为 False"

    external_fd = dream._acquire_cross_process_lock(cand_root)
    assert external_fd is not None and external_fd != dream._NO_FCNTL_FD
    try:
        assert pipe.cross_process_busy() is True, "外部持锁应为 True"
    finally:
        dream._release_cross_process_lock(external_fd)

    assert pipe.cross_process_busy() is False, "释放后应回 False"



def test_unique_tmp_contains_pid_and_is_distinct(tmp_path: Path):
    """Internal documentation."""
    target = tmp_path / "meta.json"

    for unique_tmp in (consol_mod._unique_tmp, cand_mod._unique_tmp):
        t1 = unique_tmp(target)
        t2 = unique_tmp(target)
        assert str(os.getpid()) in t1.name, f"tmp 名须含 pid: {t1.name}"
        assert t1.parent == target.parent
        assert t1.name != t2.name, "两次 _unique_tmp 不该相同"
        assert t1.name.endswith(".tmp")


def test_save_candidate_writes_no_lingering_deterministic_tmp(tmp_path: Path):
    """Internal documentation."""
    cand_root = tmp_path / "candidates"
    ws = tmp_path / "ws"
    ws.mkdir()
    d = _seed(cand_root, run="tmp00001aaaa", goal="fix login auth bug", ws=ws)
    assert (d / "SKILL.md").exists()
    assert (d / "meta.json").exists()
    assert not (d / "SKILL.md.tmp").exists()
    assert not (d / "meta.json.tmp").exists()
