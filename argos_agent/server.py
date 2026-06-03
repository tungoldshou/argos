"""FastAPI 服务:把 Argos agent 包成本地 HTTP/SSE 服务,供 Tauri 壳调用。

这一层只做「传输」:接收 goal → 跑 agent → 流式回事件。agent 的智能/护城河在 core.py。
Tauri 通过 sidecar 拉起这个服务(localhost),前端经 HTTP/SSE 调。
"""
from __future__ import annotations

import asyncio
import json
import os
import threading
import uuid
from collections import OrderedDict
from collections.abc import AsyncIterator
from contextlib import AsyncExitStack, asynccontextmanager
from dataclasses import dataclass, field
from pathlib import Path

import httpx as _httpx
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from . import approval, config, memory, mcp_client, runtime, isolation, run_registry
from .approval import ApprovalGate
from .core import build_agent_with_gate, final_text, text_delta
from .tools import ALL_TOOLS
from .verify_gate import VerifyGateMiddleware

MAX_SESSIONS = 50  # 进程内会话上限,LRU 淘汰最旧(防内存无限增长)


@dataclass
class SessionState:
    session_id: str
    verify_cmd: str | None = None
    project_dir: str | None = None
    guard: list[str] | None = None
    messages: list = field(default_factory=list)  # LangChain 消息历史(user/ai/tool)
    busy: bool = False  # 本会话是否已有一轮在跑(拒绝并发轮,防历史竞争+全局 runtime 串台)
    # 审批闸:挂在会话上,session-scope 批准("本次会话总是允许")跨轮保留;每轮结束
    # cancel_all 清空挂起项。有副作用工具执行前经它阻塞等用户决定。
    approval_gate: ApprovalGate = field(default_factory=ApprovalGate)


SESSIONS: "OrderedDict[str, SessionState]" = OrderedDict()
_SESSIONS_LOCK = threading.Lock()  # 保护 SESSIONS 的并发读改(取用/插入/淘汰)

# 并发:解除全局单飞。同会话仍串行(st.busy 护 st.messages);跨会话并发,各自 ContextVar 隔离。
MAX_CONCURRENT_RUNS = int(os.environ.get("ARGOS_MAX_CONCURRENT", "4"))  # 个位数~十几路 + 排队
_RUN_SEMAPHORE = asyncio.Semaphore(MAX_CONCURRENT_RUNS)
_LIVE_RUNS: "set[str]" = set()          # 本进程当前活跃 run_id(resume 判定:活跃则拒绝续)
_PROJECT_LOCKS: "set[str]" = set()      # 非 git 项目降级单飞:同项目同时只一个 run
_CHECKPOINTER = None                     # AsyncSqliteSaver,lifespan 起;失败=None(降级不可 resume)
CHECKPOINT_DB = Path(os.environ.get("ARGOS_CKPT_DB", Path.home() / ".argos" / "checkpoints.db"))


def _get_or_create_session(
    session_id: str | None, verify_cmd: str | None, project_dir: str | None, guard: list[str] | None
) -> SessionState:
    """取已有会话或建新会话。LRU 淘汰最旧并回收其隔离区(worktree/子目录)。"""
    evicted: list[SessionState] = []
    with _SESSIONS_LOCK:
        if session_id and session_id in SESSIONS:
            SESSIONS.move_to_end(session_id)
            return SESSIONS[session_id]
        sid = session_id or uuid.uuid4().hex[:16]
        st = SessionState(session_id=sid, verify_cmd=verify_cmd, project_dir=project_dir, guard=guard)
        SESSIONS[sid] = st
        SESSIONS.move_to_end(sid)
        while len(SESSIONS) > MAX_SESSIONS:
            _old_sid, old = SESSIONS.popitem(last=False)
            evicted.append(old)
    for old in evicted:  # 锁外回收(git subprocess 不占锁)
        try:
            if old.project_dir and isolation.is_git_project(old.project_dir):
                isolation.release_worktree(old.session_id, old.project_dir)
            elif not old.project_dir:
                isolation.release_sandbox(old.session_id)
        except Exception as e:
            # 承重墙:回收失败要可见(否则 worktree 残留会成为幽灵分支)
            import logging
            logging.getLogger(__name__).warning(
                "session LRU eviction cleanup failed: sid=%s err=%r", old.session_id, e,
            )
    return st


@asynccontextmanager
async def _lifespan(app: FastAPI):
    # 启动连一次 MCP(失败不挡服务起来:ensure_loaded 内部逐 server 降级)。
    global _CHECKPOINTER
    try:
        await mcp_client.ensure_loaded()
    except Exception:
        pass
    from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
    async with AsyncExitStack() as stack:
        try:
            CHECKPOINT_DB.parent.mkdir(parents=True, exist_ok=True)
            _CHECKPOINTER = await stack.enter_async_context(
                AsyncSqliteSaver.from_conn_string(str(CHECKPOINT_DB))
            )
        except Exception:
            _CHECKPOINTER = None  # 降级:无 checkpointer,run 照跑、只是不可 resume
        yield
    _CHECKPOINTER = None


app = FastAPI(title="Argos Agent", version="0.1.0", lifespan=_lifespan)

# CORS:前端跨 origin 调本服务时需要。两种 origin 必须都放行:
#   - dev: http://localhost:5173 (vite)
#   - 打包: tauri://localhost (macOS/Linux) 或 http://tauri.localhost (Windows)
# 关键坑:打包后 Tauri WebView 的 origin 是 tauri:// 协议,fetch 到 http://127.0.0.1
# 是跨 origin,照样触发 CORS。旧正则只匹配 https?:// → 打包后请求被拒 → 前端
# "TypeError: Load failed"(dev 好打包坏的真根因,不是 ATS)。本服务只绑 localhost,
# 仅本机可达,放开这些本地来源是安全的。
app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=r"^(https?://(localhost|127\.0\.0\.1)(:\d+)?|tauri://localhost|https?://tauri\.localhost)$",
    allow_methods=["*"],
    allow_headers=["*"],
)


# Skills 模块自己的审批闸单例 —— 跟会话的 approval_gate 分离(skills 端点是后台管理类操作,
# 不挂会话,也不需要 session-scope 跨轮缓存,任何写盘/状态变更都让用户在 UI 弹窗里点头)。
# 测试用 monkeypatch 替换 server._SKILL_GATE 即可注入自动批准/拒绝的版本。
_SKILL_GATE = approval.ApprovalGate()


class RunRequest(BaseModel):
    goal: str
    # 多轮会话:首轮空 → 后端生成 id 并经首帧回传;后续轮带上以延续上下文。
    session_id: str | None = None
    # 可选:可机检的验证命令(白名单内,如 "pytest" / "tsc")。给了就启用 verify 硬门禁:
    # agent 称"完成"必须过这条命令,否则强制重试。这是 Argos 的核心护城河。
    verify_cmd: str | None = None
    # 可选:用户自己的项目目录。给了就让 agent 在该项目里干活、跑该项目自己的测试,
    # 而非默认沙盒。这是"懂技术用户"的真实场景。
    project_dir: str | None = None
    # 可选:要保护监控篡改的文件(通常是测试文件)。project 模式下 agent 技术上能改它们,
    # 改了 run 结束会警告(篡改可见)。
    guard_files: list[str] | None = None


@app.get("/health")
def health() -> dict:
    """健康检查:Tauri 拉起 sidecar 后轮询这个确认服务就绪。"""
    return {"ok": True, "model": config.LLM_MODEL, "key_configured": bool(config.LLM_KEY)}


def _sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


def _verdict_of(gate, verify_cmd: str | None) -> str | None:
    """把门禁状态映射成三态裁决。unverifiable(篡改/不可信)优先于 failed(升级)。"""
    if not verify_cmd:
        return None
    if gate is not None and getattr(gate, "unverifiable", False):
        return "unverifiable"
    if gate is not None and getattr(gate, "escalated", False):
        return "failed"
    return "passed"


async def _consume_agent_stream(agent, gate, st, goal, stream_input, cfg):
    """驱动 agent.astream 并把事件帧转 SSE。fresh run(stream_input={"messages":...})与
    resume(stream_input=None)共用。审批挂起监视 + queue 汇聚逻辑原样保留。"""
    events: "asyncio.Queue[str | None]" = asyncio.Queue()

    async def _watch_approvals() -> None:
        seen: set[str] = set()
        try:
            while True:
                for p in st.approval_gate.pending():
                    if p.call_id not in seen:
                        seen.add(p.call_id)
                        await events.put(_sse("approval_request", {
                            "call_id": p.call_id, "tool": p.payload.get("tool"),
                            "args": p.payload.get("args"), "description": p.payload.get("description"),
                            "risk": p.payload.get("risk"),
                        }))
                await asyncio.sleep(0.05)
        except asyncio.CancelledError:
            pass

    async def _pump() -> None:
        try:
            await events.put(_sse("start", {"goal": goal}))
            final_msgs = st.messages
            astream_kwargs = {"stream_mode": ["values", "messages"]}
            if cfg is not None:
                astream_kwargs["config"] = cfg
            async for mode, chunk in agent.astream(stream_input, **astream_kwargs):
                if mode == "messages":
                    msg_chunk, _meta = chunk
                    if msg_chunk.__class__.__name__ != "AIMessageChunk":
                        continue
                    delta = text_delta(msg_chunk)
                    if delta:
                        await events.put(_sse("token", {"text": delta}))
                    continue
                msgs = chunk.get("messages", [])
                if not msgs:
                    continue
                final_msgs = msgs
                last = msgs[-1]
                kind = last.__class__.__name__
                calls = getattr(last, "tool_calls", None)
                content = str(last.content)
                if calls:
                    await events.put(_sse("tool_call", {"calls": [{"name": c["name"], "args": c["args"]} for c in calls]}))
                elif kind == "ToolMessage":
                    await events.put(_sse("tool_result", {"content": content[:2000]}))
                elif kind == "HumanMessage" and VerifyGateMiddleware.ESCALATION_TAG in content:
                    await events.put(_sse("escalation", {"detail": content[:1500]}))
                elif kind == "HumanMessage" and VerifyGateMiddleware.BOUNCE_TAG in content:
                    await events.put(_sse("verify_failed", {"detail": content[:1500]}))
                elif kind == "AIMessage":
                    txt = final_text(last)
                    if txt:
                        await events.put(_sse("message", {"text": txt}))
            st.messages = list(final_msgs)
            tampered = runtime.detect_tampering() if st.project_dir else []
            if tampered:
                await events.put(_sse("tampering", {"files": tampered}))
            verdict = _verdict_of(gate, st.verify_cmd)
            try:
                memory.record_task(goal=goal, verdict=verdict, model=config.LLM_MODEL)
            except Exception:
                pass
            if verdict == "unverifiable":
                await events.put(_sse("unverifiable", {"files": gate.tampered, "detail": gate.last_failure}))
                await events.put(_sse("done", {"resolved": False, "unverifiable": True, "attempts": gate.attempts, "tampered": gate.tampered}))
            elif verdict == "failed":
                await events.put(_sse("done", {"resolved": False, "escalated": True, "attempts": gate.attempts, "tampered": tampered}))
            else:
                await events.put(_sse("done", {"resolved": True, "tampered": tampered}))
        except Exception as e:
            await events.put(_sse("error", {"message": str(e)}))
        finally:
            await events.put(None)

    watch_task = asyncio.create_task(_watch_approvals())
    pump_task = asyncio.create_task(_pump())
    try:
        while True:
            frame = await events.get()
            if frame is None:
                break
            yield frame
    finally:
        watch_task.cancel()
        st.approval_gate.cancel_all()
        if not pump_task.done():
            pump_task.cancel()
        for t in (watch_task, pump_task):
            try:
                await t
            except (asyncio.CancelledError, Exception):
                pass


async def _run_stream(
    goal: str,
    session_id: str | None = None,
    verify_cmd: str | None = None,
    project_dir: str | None = None,
    guard: list[str] | None = None,
) -> AsyncIterator[str]:
    """跑一轮:取/建会话 → 隔离区 → per-run ContextVar → agent 流 → 落会话。
    并发:同会话串行(st.busy);跨会话并发,各自 ContextVar/worktree 隔离。"""
    st = _get_or_create_session(session_id, verify_cmd, project_dir, guard)
    with _SESSIONS_LOCK:
        if st.busy:
            yield _sse("session", {"session_id": st.session_id})
            yield _sse("error", {"message": "本会话已有一轮在跑,请等它结束。同一对话同一时刻只跑一轮。"})
            return
        st.busy = True

    # 关键:session yield / semaphore acquire 全在 try 内。客户端若在这些 yield 间断开,
    # GeneratorExit 从 yield 抛出 → 必须被 finally 覆盖,否则 busy/semaphore 永久泄漏、死锁后续
    # (沿用原代码 line 159-164 的纪律)。sem_acquired 标志让 finally 只释放真获取过的信号量。
    token = None
    project_lock_key = None
    sem_acquired = False
    run_id = uuid.uuid4().hex[:16]
    try:
        yield _sse("session", {"session_id": st.session_id})
        if _RUN_SEMAPHORE.locked():  # 已满 → 会排队,先告知前端
            yield _sse("queued", {"message": "前面有任务在跑,排队中…"})
        await _RUN_SEMAPHORE.acquire()
        sem_acquired = True

        # 隔离区:sandbox 子目录 / project worktree / 非 git 降级
        try:
            if st.project_dir:
                if isolation.is_git_project(st.project_dir):
                    ws, vd = isolation.acquire_worktree(st.session_id, st.project_dir)
                else:
                    _candidate = str(Path(st.project_dir).expanduser().resolve())
                    with _SESSIONS_LOCK:
                        if _candidate in _PROJECT_LOCKS:
                            yield _sse("error", {"message": "该项目已有任务在跑且非 git 仓库,无法隔离并发。请等待,或把项目 git init 后再并发。"})
                            return
                        _PROJECT_LOCKS.add(_candidate)
                        project_lock_key = _candidate  # 只有真加进去才记,供 finally 清(避免误删别人的锁)
                    ws = vd = Path(st.project_dir).expanduser().resolve()
                ctx = runtime.RunContext(workspace=ws, verify_dir=vd, project_mode=True)
            else:
                ws, vd = isolation.acquire_sandbox(st.session_id)
                # project_mode=True:让文件工具的 _ws() 读 ctx.workspace(per-session 子目录),
                # 否则 sandbox 隔离失效、并发 run 串回同一全局 WORKSPACE。这是承重墙的本质要求。
                # sandbox 仍是强隔离(verify_dir 在 workspace 之外,agent 够不到测试)。
                ctx = runtime.RunContext(workspace=ws, verify_dir=vd, project_mode=True)
        except isolation.IsolationError as e:
            yield _sse("error", {"message": f"隔离区创建失败,未隔离不开跑:{e}"})
            return

        token = runtime.set_context(ctx)
        if st.project_dir and st.guard:
            runtime.guard_files(st.guard)

        try:
            merged_tools = list(ALL_TOOLS) + mcp_client.mcp_tools()
            agent, gate = build_agent_with_gate(
                tools=merged_tools, verify_cmd=st.verify_cmd, goal=goal, checkpointer=_CHECKPOINTER,
            )
        except Exception as e:
            yield _sse("error", {"message": str(e)})
            return

        cfg = {"configurable": {"thread_id": run_id}} if _CHECKPOINTER is not None else None
        run_registry.open_run(
            run_id=run_id, session_id=st.session_id, thread_id=run_id,
            workspace=ws, verify_dir=vd, project_dir=st.project_dir,
            project_mode=bool(st.project_dir), guard=st.guard, goal=goal, verify_cmd=st.verify_cmd,
        )
        _LIVE_RUNS.add(run_id)

        approval_token = approval.set_current_gate(st.approval_gate)
        try:
            history = st.messages + [("user", goal)]
            async for frame in _consume_agent_stream(agent, gate, st, goal, {"messages": history}, cfg):
                yield frame
            v = _verdict_of(gate, st.verify_cmd)
            run_registry.mark(run_id, v if v in ("unverifiable", "failed") else "done")
        finally:
            approval.reset_current_gate(approval_token)
    finally:
        _LIVE_RUNS.discard(run_id)
        if token is not None:
            runtime.reset(token)
        if project_lock_key is not None:
            with _SESSIONS_LOCK:
                _PROJECT_LOCKS.discard(project_lock_key)
        if sem_acquired:
            _RUN_SEMAPHORE.release()
        with _SESSIONS_LOCK:
            st.busy = False


@app.get("/mcp/servers")
async def mcp_servers() -> dict:
    """前端据此渲染真实 MCP 连接态(连不上显 disconnected,不再假 connected)。"""
    await mcp_client.ensure_loaded()
    return {"servers": mcp_client.server_status()}


@app.get("/memory")
def get_memory() -> dict:
    """Argos 自己跑过的任务记忆(真实、随任务生长)。前端据此构建记忆大脑图。
    没有记忆 → 空列表,前端显示诚实空态,而非编造假记忆。"""
    return {"records": memory.load_memories()}


# ── skills 管理端点 ─────────────────────────────────────────────────────────
# 读 /skills 公开;写 /skills/import 与 /skills/{name}/toggle 走 _SKILL_GATE —— 写盘与改状态
# 都是有副作用,必须让用户在弹窗里点头。gate 上下文通过 ContextVar 设定,跟 MCP/run 流同套路。
from . import skills as _skills  # 本地别名,避免覆盖 server 模块其它可能的 skills 名字


@app.get("/skills")
def get_skills() -> dict:
    """列所有 skill(name/desc/trust/enabled/source),不触发 embedding。"""
    out = [s.to_dict() for s in _skills.load_all()]
    return {"skills": out}


@app.post("/skills/import")
async def import_skill(body: dict) -> dict:
    """导入一个新 skill。body: {url?: str, content?: str, trust?: str, source?: str}。
    url 与 content 二选一;url 走 httpx 拉回,content 直接接正文。
    整个动作写盘=有副作用,必走 _SKILL_GATE;通过后落地并刷 recall 缓存。"""
    token = approval.set_current_gate(_SKILL_GATE)
    try:
        if body.get("url") and not body.get("content"):
            try:
                r = _httpx.get(str(body["url"]), timeout=15.0, follow_redirects=True)
            except Exception as e:
                raise HTTPException(status_code=400, detail=f"fetch failed: {e!r}")
            if r.status_code != 200:
                raise HTTPException(status_code=400, detail=f"http {r.status_code}")
            content = r.text
            source = str(body["url"])
        elif body.get("content"):
            content = body["content"]
            source = body.get("source", "inline")
        else:
            raise HTTPException(status_code=400, detail="need url or content")

        payload = {
            "tool": "skills.import",
            "args": {"source": source, "len": len(content)},
            "description": f"导入 skill: {source}",
            "risk": "medium",
            "source": "skill:import",
        }
        decision = await _SKILL_GATE.request(payload)
        if not decision.approved:
            return {"ok": False, "reason": decision.reason or "denied"}
        try:
            s = _skills.import_skill(content=content, source=source)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))
        return {"ok": True, "skill": s.to_dict()}
    finally:
        approval.reset_current_gate(token)


@app.post("/skills/{name}/toggle")
async def toggle_skill(name: str, body: dict) -> dict:
    """切换 skill.enabled。改状态=有副作用,必走 _SKILL_GATE。"""
    token = approval.set_current_gate(_SKILL_GATE)
    try:
        enabled = bool(body.get("enabled", True))
        payload = {
            "tool": "skills.toggle",
            "args": {"name": name, "enabled": enabled},
            "description": f"{'启用' if enabled else '禁用'} skill: {name}",
            "risk": "low",
            "source": f"skill:{name}",
        }
        decision = await _SKILL_GATE.request(payload)
        if not decision.approved:
            return {"ok": False, "reason": decision.reason or "denied"}
        ok = _skills.toggle(name, enabled=enabled)
        return {"ok": ok}
    finally:
        approval.reset_current_gate(token)


@app.post("/run")
async def run(req: RunRequest) -> StreamingResponse:
    return StreamingResponse(
        _run_stream(req.goal, req.session_id, req.verify_cmd, req.project_dir, req.guard_files),
        media_type="text/event-stream",
    )


class PlanRequest(BaseModel):
    """plan 拆大活的入口请求。"""
    goal: str
    session_id: str | None = None
    project_dir: str | None = None  # 可选:project 模式(plan 拆出来的每 task 在自己的 worktree 分支)


@app.post("/plan")
async def plan_run(body: PlanRequest) -> StreamingResponse:
    """接收 goal,planner 拆活 → 派 worker → 报告。返 SSE 流,
    事件形状与 orchestrator 一致:plan:start / plan:tasks / task:start / task:verdict / plan:report / plan:escalate。"""
    from . import orchestrator as _orch

    sid = body.session_id or uuid.uuid4().hex[:16]

    async def _gen() -> AsyncIterator[str]:
        started = False
        try:
            async for ev in _orch.run_plan(goal=body.goal, session_id=sid, project_dir=body.project_dir):
                started = True
                yield _sse(ev["type"], ev)
        except Exception as e:
            if not started:
                # plan:start 都没发出 → 立即出 escalate + report
                yield _sse("plan:start", {"goal": body.goal, "session_id": sid})
            yield _sse("plan:escalate", {"reason": f"orchestrator: {e!r}"})
            yield _sse("plan:report", {"split": 0, "succeeded": 0, "failed": 0, "status": "error"})

    return StreamingResponse(_gen(), media_type="text/event-stream")


# 续跑(从 registry 重建 RunContext + thread_id 续 checkpoint):
#   · 在 _LIVE_RUNS=仍在跑(409);registry 无=404;终态=400;无 checkpointer=503。
#   · 与 _run_stream 共享 _consume_agent_stream(stream_input=None, cfg=thread_id 续)。
#   · 注意两套 project_mode 语义(关键防串台):
#       - run_registry 存的 rec["project_mode"] = 是否走 project 模式(用于决定是否 guard)。
#       - RunContext.project_mode = "工具 _ws() 读 ctx vs 回退模块默认 WORKSPACE"。
#     resume 重建 RunContext 时必须 project_mode=True:sandbox run rec 存 False,resume
#     若照搬,tools._ws() 会回退到模块默认 WORKSPACE,破隔离。rec["project_mode"] 仍作
#     "要不要 guard" 的判据。
@app.post("/run/{run_id}/resume")
async def resume_run(run_id: str) -> StreamingResponse:
    """续跑一个被中断的 run:从 registry 重建 RunContext + thread_id,续 checkpoint。
    判定:在 _LIVE_RUNS=仍在跑(409);registry 无=404;终态=400;否则 astream(None) 续。"""
    if run_id in _LIVE_RUNS:
        raise HTTPException(status_code=409, detail="该任务仍在运行,无需恢复")
    rec = run_registry.get(run_id)
    if rec is None:
        raise HTTPException(status_code=404, detail="未知 run_id")
    if rec["status"] in ("done", "failed", "unverifiable"):
        raise HTTPException(status_code=400, detail=f"该任务已结束({rec['status']}),无可恢复")
    if _CHECKPOINTER is None:
        raise HTTPException(status_code=503, detail="checkpointer 未就绪,无法恢复")

    async def _gen() -> AsyncIterator[str]:
        # 重建会话外壳(重启后 SESSIONS 可能没了 → 造个临时承载 st.messages/approval_gate)
        st = _get_or_create_session(rec["session_id"], rec["verify_cmd"], rec["project_dir"] or None, rec["guard"])
        with _SESSIONS_LOCK:
            if st.busy:
                yield _sse("error", {"message": "会话忙,稍后再试"})
                return
            st.busy = True
        token = None
        sem_acquired = False
        try:
            await _RUN_SEMAPHORE.acquire()  # 在 try 内:acquire 被取消也不漏 busy
            sem_acquired = True
            # 强制 project_mode=True:让 tools._ws() 读 ctx(per-run 隔离区),不回退模块默认 WORKSPACE
            # (sandbox run rec 存的是 False,若照搬会破隔离,见端点 docstring)
            ctx = runtime.RunContext(
                workspace=Path(rec["workspace"]), verify_dir=Path(rec["verify_dir"]),
                project_mode=True,
            )
            token = runtime.set_context(ctx)
            if rec["project_mode"] and rec["guard"]:
                runtime.guard_files(rec["guard"])
            merged_tools = list(ALL_TOOLS) + mcp_client.mcp_tools()
            agent, gate = build_agent_with_gate(
                tools=merged_tools, verify_cmd=rec["verify_cmd"], goal=rec["goal"], checkpointer=_CHECKPOINTER,
            )
            cfg = {"configurable": {"thread_id": rec["thread_id"]}}
            _LIVE_RUNS.add(run_id)
            approval_token = approval.set_current_gate(st.approval_gate)
            try:
                yield _sse("session", {"session_id": st.session_id})
                yield _sse("resumed", {"run_id": run_id})
                async for frame in _consume_agent_stream(agent, gate, st, rec["goal"], None, cfg):
                    yield frame
                v = _verdict_of(gate, rec["verify_cmd"])
                run_registry.mark(run_id, v if v in ("unverifiable", "failed") else "done")
            finally:
                approval.reset_current_gate(approval_token)
        finally:
            _LIVE_RUNS.discard(run_id)
            if token is not None:
                runtime.reset(token)
            if sem_acquired:
                _RUN_SEMAPHORE.release()
            with _SESSIONS_LOCK:
                st.busy = False

    return StreamingResponse(_gen(), media_type="text/event-stream")


class ApproveRequest(BaseModel):
    """用户对某次工具调用的审批决定。"""
    call_id: str
    decision: str  # "approve" | "deny"
    scope: str = "once"  # "once" | "session"(仅 approve 用)
    reason: str = ""  # 仅 deny 用,会回传给模型让它换路


@app.post("/run/{session_id}/approve")
def approve_call(session_id: str, body: ApproveRequest) -> dict:
    """用户拍板某次有副作用的工具调用。approve→放行(可选整会话默许);deny→拒绝。
    返回 ok=False 表示该 call_id 已不在挂起(超时/被取消/重复点),前端可据此收起弹窗。"""
    with _SESSIONS_LOCK:
        st = SESSIONS.get(session_id)
    if st is None:
        raise HTTPException(status_code=404, detail="session 不存在")
    if body.decision == "approve":
        scope = body.scope if body.scope in ("once", "session") else "once"
        ok = st.approval_gate.approve(body.call_id, scope=scope)  # type: ignore[arg-type]
    elif body.decision == "deny":
        ok = st.approval_gate.deny(body.call_id, reason=body.reason)
    else:
        raise HTTPException(status_code=400, detail="decision 必须是 approve 或 deny")
    return {"ok": ok}
