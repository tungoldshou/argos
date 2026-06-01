"""FastAPI 服务:把 Argos agent 包成本地 HTTP/SSE 服务,供 Tauri 壳调用。

这一层只做「传输」:接收 goal → 跑 agent → 流式回事件。agent 的智能/护城河在 core.py。
Tauri 通过 sidecar 拉起这个服务(localhost),前端经 HTTP/SSE 调。
"""
from __future__ import annotations

import json
import threading
import uuid
from collections import OrderedDict
from collections.abc import AsyncIterator
from dataclasses import dataclass, field

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from . import config, memory, runtime
from .core import build_agent_with_gate, final_text, text_delta
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


app = FastAPI(title="Argos Agent", version="0.1.0")

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
    # 首帧回传 session_id,前端存下供后续轮。注意:紧跟其后可能立即来一个 error
    # 事件(如缺 key 配置),客户端无论如何都应先存下这个 id。
    yield _sse("session", {"session_id": st.session_id})

    try:
        # 切运行时上下文(用会话锁定的值,非本轮请求值)。
        if st.project_dir:
            runtime.use_project(st.project_dir)
            if st.guard:
                runtime.guard_files(st.guard)
        else:
            runtime.use_sandbox()
        try:
            agent, gate = build_agent_with_gate(verify_cmd=st.verify_cmd, goal=goal)
        except Exception as e:
            yield _sse("error", {"message": str(e)})
            runtime.use_sandbox()
            return

        yield _sse("start", {"goal": goal})
        history = st.messages + [("user", goal)]
        final_msgs = st.messages
        try:
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
                        yield _sse("token", {"text": delta})
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
                    yield _sse("tool_call", {"calls": [{"name": c["name"], "args": c["args"]} for c in calls]})
                elif kind == "ToolMessage":
                    yield _sse("tool_result", {"content": content[:2000]})
                elif kind == "HumanMessage" and VerifyGateMiddleware.ESCALATION_TAG in content:
                    yield _sse("escalation", {"detail": content[:1500]})
                elif kind == "HumanMessage" and VerifyGateMiddleware.BOUNCE_TAG in content:
                    yield _sse("verify_failed", {"detail": content[:1500]})
                elif kind == "AIMessage":
                    txt = final_text(last)
                    if txt:
                        # message 仍发:作为该段答复的权威定稿,前端用它覆盖累积的 token(防漂移)。
                        yield _sse("message", {"text": txt})
            # 本轮跑完:把完整消息历史落回会话,供下一轮延续上下文。
            st.messages = list(final_msgs)
            tampered = runtime.detect_tampering() if st.project_dir else []
            if tampered:
                yield _sse("tampering", {"files": tampered})
            escalated = bool(gate and gate.escalated)
            unverifiable = bool(gate and getattr(gate, "unverifiable", False))
            verdict = _verdict_of(gate, st.verify_cmd)
            try:
                memory.record_task(goal=goal, verdict=verdict, model=config.LLM_MODEL)
            except Exception:
                pass
            if unverifiable:
                yield _sse("unverifiable", {"files": gate.tampered, "detail": gate.last_failure})
                yield _sse("done", {"resolved": False, "unverifiable": True, "tampered": gate.tampered})
            elif escalated:
                yield _sse("done", {"resolved": False, "escalated": True, "attempts": gate.attempts, "tampered": tampered})
            else:
                yield _sse("done", {"resolved": True, "tampered": tampered})
        except Exception as e:
            yield _sse("error", {"message": str(e)})
    finally:
        # 本轮无论怎么结束(正常/异常/早退)都释放 busy + 全局单飞标志,否则会话/全局会被永久锁死。
        # 这个 finally 必须万无一失:泄漏 _RUN_ACTIVE=True 会死锁所有后续 run。
        with _SESSIONS_LOCK:
            st.busy = False
            _RUN_ACTIVE = False


@app.get("/memory")
def get_memory() -> dict:
    """Argos 自己跑过的任务记忆(真实、随任务生长)。前端据此构建记忆大脑图。
    没有记忆 → 空列表,前端显示诚实空态,而非编造假记忆。"""
    return {"records": memory.load_memories()}


@app.post("/run")
async def run(req: RunRequest) -> StreamingResponse:
    return StreamingResponse(
        _run_stream(req.goal, req.session_id, req.verify_cmd, req.project_dir, req.guard_files),
        media_type="text/event-stream",
    )
