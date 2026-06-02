"""FastAPI 服务:把 Argos agent 包成本地 HTTP/SSE 服务,供 Tauri 壳调用。

这一层只做「传输」:接收 goal → 跑 agent → 流式回事件。agent 的智能/护城河在 core.py。
Tauri 通过 sidecar 拉起这个服务(localhost),前端经 HTTP/SSE 调。
"""
from __future__ import annotations

import asyncio
import json
import threading
import uuid
from collections import OrderedDict
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field

import httpx as _httpx
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from . import approval, config, memory, mcp_client, runtime
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
_RUN_ACTIVE = False  # 全局单飞:同一时刻只允许一个 run 执行(runtime._current 是进程级全局,
                     # 并发 run 会串台,破坏沙盒隔离/篡改可见保证)。第二个并发 run 诚实拒绝。


def _get_or_create_session(
    session_id: str | None, verify_cmd: str | None, project_dir: str | None, guard: list[str] | None
) -> SessionState:
    """取已有会话(setup 首轮锁定,后续参数忽略)或建新会话。LRU 淘汰最旧。"""
    with _SESSIONS_LOCK:
        if session_id and session_id in SESSIONS:
            SESSIONS.move_to_end(session_id)  # 标记为最近使用
            return SESSIONS[session_id]
        sid = session_id or uuid.uuid4().hex[:16]  # 16 hex = 64 bits,对 ≤50 个会话足够,碰撞可忽略
        st = SessionState(session_id=sid, verify_cmd=verify_cmd, project_dir=project_dir, guard=guard)
        SESSIONS[sid] = st
        SESSIONS.move_to_end(sid)
        while len(SESSIONS) > MAX_SESSIONS:
            SESSIONS.popitem(last=False)  # 淘汰最旧
        return st


@asynccontextmanager
async def _lifespan(app: FastAPI):
    # 启动连一次 MCP(失败不挡服务起来:ensure_loaded 内部逐 server 降级)。
    try:
        await mcp_client.ensure_loaded()
    except Exception:
        pass
    yield


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


async def _run_stream(
    goal: str,
    session_id: str | None = None,
    verify_cmd: str | None = None,
    project_dir: str | None = None,
    guard: list[str] | None = None,
) -> AsyncIterator[str]:
    """跑一轮:取/建会话 → 用历史+本轮消息跑 agent → 流式回事件 → 新消息落回会话。
    verify/project/guard 在会话首轮锁定,后续轮继承。"""
    global _RUN_ACTIVE
    st = _get_or_create_session(session_id, verify_cmd, project_dir, guard)
    with _SESSIONS_LOCK:
        if st.busy or _RUN_ACTIVE:
            # 已有一轮在跑(本会话 st.busy,或任意会话 _RUN_ACTIVE):拒绝并发轮。
            # runtime._current 是进程级全局,并发 run 会串台 → 破坏沙盒隔离/篡改可见保证。
            # 诚实拒绝,不静默丢历史。
            yield _sse("session", {"session_id": st.session_id})
            yield _sse("error", {"message": "当前已有一个任务在运行,请等它结束再继续。Argos 同一时刻只跑一个任务,以保证沙盒隔离。"})
            return
        st.busy = True
        _RUN_ACTIVE = True
    try:
        # 首帧回传 session_id,前端存下供后续轮。注意:紧跟其后可能立即来一个 error
        # 事件(如缺 key 配置),客户端无论如何都应先存下这个 id。
        # 这一步必须在 try 内:客户端若在 session→start 窗口断开,GeneratorExit 会从这个
        # yield 抛出,只有被 try 覆盖 finally 才会跑、释放 _RUN_ACTIVE —— 否则永久泄漏、
        # 死锁后续所有 run(并发单飞标志再也回不到 False)。
        yield _sse("session", {"session_id": st.session_id})

        # 切运行时上下文(用会话锁定的值,非本轮请求值)。
        if st.project_dir:
            runtime.use_project(st.project_dir)
            if st.guard:
                runtime.guard_files(st.guard)
        else:
            runtime.use_sandbox()
        try:
            # MCP 工具在 lifespan 启动时已连好并缓存;这里直接取缓存(未加载则为空,退化成
            # 只有内置工具)。**不在此处 ensure_loaded**:lifespan 早于"接受请求"就跑完,生产
            # 路径工具已就绪;而在 run 路径连 MCP 会让所有直接驱动 _run_stream 的测试触发真实
            # npx 连接(慢/flaky)。run 路径只读缓存,绝不在这里发起连接。
            merged_tools = list(ALL_TOOLS) + mcp_client.mcp_tools()
            agent, gate = build_agent_with_gate(
                tools=merged_tools, verify_cmd=st.verify_cmd, goal=goal,
            )
        except Exception as e:
            yield _sse("error", {"message": str(e)})
            runtime.use_sandbox()
            return

        # 审批闸装进上下文:被 @requires_approval 标记的工具在本轮能找到本会话的 gate。
        # 必须在 create_task(pump) 之前设好 —— ContextVar 在建任务那刻被复制进子任务。
        approval_token = approval.set_current_gate(st.approval_gate)
        # 工具阻塞等审批时,agent.astream 会整体挂起,消费侧卡在 async for 取不到帧。
        # 用 queue 把「agent 事件流」和「审批挂起监视」两个并发源汇聚,生成器统一 drain。
        events: "asyncio.Queue[str | None]" = asyncio.Queue()

        async def _watch_approvals() -> None:
            """并发监视审批挂起项,新出现的推 approval_request 给前端(否则工具阻塞期间
            前端收不到弹窗请求)。轮询而非回调:回调会在工具的执行线程触发,跨 loop 操作
            主 loop 的 queue 不安全;轮询读 pending() 字典是安全的。"""
            seen: set[str] = set()
            try:
                while True:
                    for p in st.approval_gate.pending():
                        if p.call_id not in seen:
                            seen.add(p.call_id)
                            await events.put(_sse("approval_request", {
                                "call_id": p.call_id,
                                "tool": p.payload.get("tool"),
                                "args": p.payload.get("args"),
                                "description": p.payload.get("description"),
                                "risk": p.payload.get("risk"),
                            }))
                    await asyncio.sleep(0.05)
            except asyncio.CancelledError:
                pass

        async def _pump() -> None:
            """跑 agent,把事件帧推进 queue;无论如何结束都以 None 哨兵收尾。"""
            try:
                await events.put(_sse("start", {"goal": goal}))
                history = st.messages + [("user", goal)]
                final_msgs = st.messages
                async for mode, chunk in agent.astream(
                    {"messages": history}, stream_mode=["values", "messages"]
                ):
                    if mode == "messages":
                        # chunk = (message_chunk, metadata)。messages 模式实际只产 AIMessageChunk;
                        # 但防御性卡 class:HumanMessage/ToolMessage 的 content 是字符串(text_delta 会原样返回),
                        # 若漏进 messages 流会把用户输入/工具结果当 token 外发。
                        msg_chunk, _meta = chunk
                        if msg_chunk.__class__.__name__ != "AIMessageChunk":
                            continue
                        delta = text_delta(msg_chunk)
                        if delta:
                            await events.put(_sse("token", {"text": delta}))
                        continue
                    # mode == "values":完整 state,驱动 tool/verify/escalation 检测 + message 定稿。
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
                            # message 仍发:作为该段答复的权威定稿,前端用它覆盖累积的 token(防漂移)。
                            await events.put(_sse("message", {"text": txt}))
                # 本轮跑完:把完整消息历史落回会话,供下一轮延续上下文。
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
            # 收束顺序要紧:先 cancel_all 把任何挂起审批以 deny 解除(否则 pump 永远卡在
            # 工具的 await gate.request),工具拿到 deny 字符串后 astream 才能自然收尾。
            watch_task.cancel()
            st.approval_gate.cancel_all()
            approval.reset_current_gate(approval_token)
            if not pump_task.done():
                pump_task.cancel()
            for t in (watch_task, pump_task):
                try:
                    await t
                except (asyncio.CancelledError, Exception):
                    pass
    finally:
        # 本轮无论怎么结束(正常/异常/早退)都释放 busy + 全局单飞标志,否则会话/全局会被永久锁死。
        # 这个 finally 必须万无一失:泄漏 _RUN_ACTIVE=True 会死锁所有后续 run。
        with _SESSIONS_LOCK:
            st.busy = False
            _RUN_ACTIVE = False


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
