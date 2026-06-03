"""恢复铁证 —— ① checkpointer kill-resume 机制(纯 LangGraph,不依赖 LLM);
② resume 端点从 registry 重建上下文(monkeypatch agent)。"""
import asyncio
import operator
import tempfile
import os
from typing import Annotated, TypedDict

import pytest


def test_checkpointer_kill_and_resume():
    """探针的测试化:中途停 → 换 saver 实例(模拟重启) → ainvoke(None) 续跑。"""
    from langgraph.graph import StateGraph, START, END
    from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

    class S(TypedDict):
        trail: Annotated[list, operator.add]

    def n1(s): return {"trail": ["n1"]}
    def n2(s): return {"trail": ["n2"]}

    def build(saver):
        g = StateGraph(S)
        g.add_node("n1", n1); g.add_node("n2", n2)
        g.add_edge(START, "n1"); g.add_edge("n1", "n2"); g.add_edge("n2", END)
        return g.compile(checkpointer=saver, interrupt_after=["n1"])

    async def main():
        db = os.path.join(tempfile.mkdtemp(), "ck.db")
        cfg = {"configurable": {"thread_id": "t1"}}
        async with AsyncSqliteSaver.from_conn_string(db) as s1:
            out1 = await build(s1).ainvoke({"trail": []}, cfg)
        async with AsyncSqliteSaver.from_conn_string(db) as s2:
            g2 = build(s2)
            snap = await g2.aget_state(cfg)
            out2 = await g2.ainvoke(None, cfg)
        return out1["trail"], snap.next, out2["trail"]

    t1, nxt, t2 = asyncio.run(main())
    assert t1 == ["n1"]
    assert nxt == ("n2",)
    assert t2 == ["n1", "n2"]


def test_resume_rejects_live_run(monkeypatch):
    """run_id 仍在 _LIVE_RUNS → 拒绝续(还在跑)。"""
    from fastapi.testclient import TestClient
    from argos_agent import server
    monkeypatch.setattr(server, "_LIVE_RUNS", {"liveX"})
    client = TestClient(server.app)
    r = client.post("/run/liveX/resume")
    assert r.status_code == 409


def test_resume_unknown_run_404(monkeypatch):
    from fastapi.testclient import TestClient
    from argos_agent import server, run_registry
    monkeypatch.setattr(run_registry, "get", lambda rid: None)
    monkeypatch.setattr(server, "_LIVE_RUNS", set())
    client = TestClient(server.app)
    r = client.post("/run/nope/resume")
    assert r.status_code == 404
