"""并发铁证 —— 两 run 同进程并发、各写各的隔离区、互不污染;semaphore 排队。"""
import asyncio
import pytest

from argos_agent import server, runtime, isolation


def test_run_semaphore_exists_and_default():
    assert isinstance(server._RUN_SEMAPHORE, asyncio.Semaphore)
    assert server.MAX_CONCURRENT_RUNS >= 2


def test_run_active_global_removed():
    """全局单飞标志已删 —— 不再有 _RUN_ACTIVE 进程级锁。"""
    assert not hasattr(server, "_RUN_ACTIVE")


def test_two_contexts_write_isolated_dirs(tmp_path, monkeypatch):
    """两个并发 task 各 set_context 不同 sandbox,各跑 write_file,各写各的目录、互不可见。
    这是承重墙在真实工具上的端到端隔离证据。"""
    from argos_agent import tools, approval
    monkeypatch.setattr(isolation, "RUNS_ROOT", tmp_path / "runs")

    # 装一个 auto-approve gate(write_file 需审批)
    gate = approval.ApprovalGate()
    async def auto(payload, timeout=60.0):
        return approval.Decision(approved=True, scope="once")
    gate.request = auto  # type: ignore[assignment]

    async def worker(tag: str):
        ws, vd = isolation.acquire_sandbox(f"sess-{tag}")
        # project_mode=True:文件工具的 _ws() 只在该模式读 ctx.workspace(per-session 子目录),
        # 否则回退模块级 WORKSPACE、隔离失效。server._run_stream 的 sandbox 分支同此设置。
        token = runtime.set_context(runtime.RunContext(workspace=ws, verify_dir=vd, project_mode=True))
        gtoken = approval.set_current_gate(gate)
        try:
            await tools.write_file.ainvoke({"path": f"{tag}.txt", "content": tag})
            await asyncio.sleep(0.01)
            # 只能看到自己写的文件,看不到对方的
            names = {p.name for p in ws.iterdir()}
            return names
        finally:
            approval.reset_current_gate(gtoken)
            runtime.reset(token)

    async def main():
        return await asyncio.gather(worker("A"), worker("B"))

    a_names, b_names = asyncio.run(main())
    assert "A.txt" in a_names and "B.txt" not in a_names
    assert "B.txt" in b_names and "A.txt" not in b_names
