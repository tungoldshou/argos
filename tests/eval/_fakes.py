"""eval 测试 fake 桩:FakeWorktree + make_fake_loop,供 test_eval_runner / test_eval_compare 复用。

(conftest discovery 在多目录项目里不可靠;改用 import-based 共享。)"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from argos_agent.eval.runner import (
    LoopOutcome,
    PASS_PASSED, PASS_FAILED, PASS_UNVERIFIABLE, PASS_SETUP_FAILED, PASS_ERROR,
)


class FakeWorktree:
    """在 tmp_path/eval_wt/<run_id>/ 落目录,模拟 worktree create/cleanup。"""
    def __init__(self, base: Path, *, fail_create: bool = False):
        self.base = Path(base)
        self.base.mkdir(parents=True, exist_ok=True)
        self._fail_create = fail_create
        self.created: list[str] = []
        self.cleaned: list[str] = []

    def is_git_repo(self, workspace: str) -> bool:
        return True

    def create(self, *, run_id: str, workspace: str) -> str:
        if self._fail_create:
            raise RuntimeError("simulated worktree failure")
        p = self.base / run_id
        p.mkdir(parents=True, exist_ok=True)
        (p / "sentinel.txt").write_text(f"from {workspace}", encoding="utf-8")
        self.created.append(run_id)
        return str(p)

    def cleanup(self, run_id: str) -> None:
        import shutil
        p = self.base / run_id
        if p.exists():
            shutil.rmtree(p, ignore_errors=True)
        self.cleaned.append(run_id)


def make_fake_loop(
    *,
    verdict: str = PASS_PASSED,
    detail: str = "5 passed in 0.5s",
    tampered: tuple[str, ...] = (),
    tokens_in: int = 1000,
    tokens_out: int = 500,
    cost_usd: float | None = 0.013,
    steps: int = 8,
    raise_on_run: bool = False,
):
    """返一个 fake loop:有 run_sync(goal, workspace) → LoopOutcome。"""
    class _Loop:
        pass

    loop = _Loop()
    loop.steps = 0
    loop.tokens_in = 0
    loop.tokens_out = 0
    loop.cost_usd = 0.0

    def _run_sync(goal: str, workspace: Path) -> LoopOutcome:
        if raise_on_run:
            raise RuntimeError("simulated LLM failure")
        loop.steps = steps
        loop.tokens_in = tokens_in
        loop.tokens_out = tokens_out
        loop.cost_usd = cost_usd
        return LoopOutcome(
            verdict_status=verdict, verify_detail=detail, tampered=tampered,
            steps=steps, tokens_in=tokens_in, tokens_out=tokens_out,
            cost_usd=cost_usd,
        )

    loop.run_sync = _run_sync
    return loop


def make_fake_loop_factory(loop):
    def _factory(model_tier: str):
        return loop
    return _factory
