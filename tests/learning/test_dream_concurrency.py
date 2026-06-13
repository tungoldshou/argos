"""review#4 回归守卫:Dream 跨进程并发 —— 文件锁 + 进程唯一 .tmp 名。

病灶(已亲验):
- 单飞锁是 per-instance asyncio.Lock(跨进程不可见);
- CLI 独立进程每次新建 DreamPipeline,daemon 持单例 → 两进程并发无互斥;
- 所有原子写用确定性 *.tmp 后缀 → 同名 tmp 互相覆盖 → 撕裂写损坏不可硬删的记忆。

修法两件:
1) DreamPipeline.run() 入口抢一个从 candidates_root 派生的跨进程 fcntl 文件锁;
   抢不到 → run() 返 None(与既有单飞语义一致)。
2) consolidate/candidates/promotion_gate 所有原子写 .tmp 改成 pid+uuid 唯一名。

回退验证(硬要求):
- 去掉锁 → test_run_skips_when_external_holder_owns_lock 不再返 None(FAIL);
- 确定性 .tmp → test_atomic_tmp_unique_name 的 pid/唯一性断言 FAIL。
"""
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

# fcntl 仅 unix;本项目主线 macOS/linux。非 unix 平台直接跳过跨进程锁断言。
fcntl = pytest.importorskip("fcntl")


# ── helper:种候选 ─────────────────────────────────────────────────────────────

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


# ── test 1: 锁获取函数的 fcntl 互斥语义(同进程两 fd 验互斥) ──────────────────

def test_acquire_cross_process_lock_is_mutually_exclusive(tmp_path: Path):
    """从同一 candidates_root 派生的锁:第一个持锁期间第二个抢不到(返 None)。

    回退验证:去掉 flock,第二次 _acquire_cross_process_lock 不再返 None。
    """
    cand_root = tmp_path / "candidates"

    fd1 = dream._acquire_cross_process_lock(cand_root)
    assert fd1 is not None and fd1 != dream._NO_FCNTL_FD, "首个应抢到真锁"

    # 第二个抢同一锁路径 → 立刻非阻塞失败 → None
    fd2 = dream._acquire_cross_process_lock(cand_root)
    assert fd2 is None, "持锁期间第二个必须抢不到(返 None)"

    # 释放第一个 → 第三个能抢到
    dream._release_cross_process_lock(fd1)
    fd3 = dream._acquire_cross_process_lock(cand_root)
    assert fd3 is not None and fd3 != dream._NO_FCNTL_FD, "释放后应可重抢"
    dream._release_cross_process_lock(fd3)


def test_lock_path_isolated_per_candidates_root(tmp_path: Path):
    """两个不同 candidates_root → 锁路径不同 → 互不阻塞(测试注入 tmp 隔离)。"""
    root_a = tmp_path / "a" / "candidates"
    root_b = tmp_path / "b" / "candidates"
    fd_a = dream._acquire_cross_process_lock(root_a)
    fd_b = dream._acquire_cross_process_lock(root_b)
    try:
        assert fd_a is not None and fd_a != dream._NO_FCNTL_FD
        assert fd_b is not None and fd_b != dream._NO_FCNTL_FD, (
            "不同 candidates_root 的锁应互不阻塞"
        )
        # 锁文件落在 candidates_root.parent
        assert dream._lock_path_for(root_a) == root_a.parent / dream.DREAM_LOCK_NAME
    finally:
        dream._release_cross_process_lock(fd_a)
        dream._release_cross_process_lock(fd_b)


# ── test 2: run() 在外部持锁时跳过(跨进程单飞) ───────────────────────────────

def test_run_skips_when_external_holder_owns_lock(tmp_path: Path):
    """模拟另一进程已持锁:对同一 candidates_root 先 _acquire,再跑 run() → 返 None。

    回退验证:撤掉 run() 里的跨进程锁,本测试 run() 会真跑出 DreamReport(非 None)→ FAIL。
    """
    cand_root = tmp_path / "candidates"
    ws = tmp_path / "ws"
    ws.mkdir()
    _seed(cand_root, run="ext00001aaaa", goal="fix login auth bug", ws=ws)

    # "另一进程"先持锁
    external_fd = dream._acquire_cross_process_lock(cand_root)
    assert external_fd is not None and external_fd != dream._NO_FCNTL_FD

    pipe = _make_pipeline(tmp_path)
    try:
        report = asyncio.run(pipe.run())
        assert report is None, "外部持锁期间 run() 必须返 None(跨进程单飞)"
        # 外部持锁期间候选区不应被消费(没真跑)
        from argos.learning.candidates import list_unconsumed
        assert len(list_unconsumed(cand_root)) == 1, "未跑就不该消费候选"
    finally:
        dream._release_cross_process_lock(external_fd)

    # 释放外部锁后再跑 → 这次真跑(返非 None)
    report2 = asyncio.run(pipe.run())
    assert report2 is not None, "外部锁释放后 run() 应能真跑"


def test_cross_process_busy_probe_reflects_external_holder(tmp_path: Path):
    """cross_process_busy() 探针:外部持锁 → True;释放 → False。

    daemon _start_dream 用它在派生任务前预检 → 409 dream_busy(不回 202 却没跑)。
    """
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


# ── test 3: 原子写 .tmp 名进程唯一 ───────────────────────────────────────────

def test_unique_tmp_contains_pid_and_is_distinct(tmp_path: Path):
    """consolidate / candidates 的 _unique_tmp:名含 pid 且两次调用互不相同。

    回退验证:确定性 .tmp 后缀 → 名不含 pid / 两次相同 → 断言 FAIL。
    """
    target = tmp_path / "meta.json"

    for unique_tmp in (consol_mod._unique_tmp, cand_mod._unique_tmp):
        t1 = unique_tmp(target)
        t2 = unique_tmp(target)
        # 含 pid(跨进程不撞)
        assert str(os.getpid()) in t1.name, f"tmp 名须含 pid: {t1.name}"
        # 同目录(replace 才原子)
        assert t1.parent == target.parent
        # 两次唯一(uuid 段不同)
        assert t1.name != t2.name, "两次 _unique_tmp 不该相同"
        # 仍以 .tmp 结尾
        assert t1.name.endswith(".tmp")


def test_save_candidate_writes_no_lingering_deterministic_tmp(tmp_path: Path):
    """save_candidate 落盘后:目标文件齐全,无残留确定性 'SKILL.md.tmp' / 'meta.json.tmp'。"""
    cand_root = tmp_path / "candidates"
    ws = tmp_path / "ws"
    ws.mkdir()
    d = _seed(cand_root, run="tmp00001aaaa", goal="fix login auth bug", ws=ws)
    # 目标文件齐
    assert (d / "SKILL.md").exists()
    assert (d / "meta.json").exists()
    # 旧确定性 tmp 名不该存在(replace 后清理 + 不应被并发覆盖)
    assert not (d / "SKILL.md.tmp").exists()
    assert not (d / "meta.json.tmp").exists()
