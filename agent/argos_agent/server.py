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
from .core import build_agent_with_gate, final_text
from .verify_gate import VerifyGateMiddleware

MAX_SESSIONS = 50  # 进程内会话上限,LRU 淘汰最旧(防内存无限增长)


@dataclass
class SessionState:
    session_id: str
    verify_cmd: str | None = None
    project_dir: str | None = None
    guard: list[str] | None = None
    messages: list = field(default_factory=list)  # LangChain 消息历史(user/ai/tool)
    gate: "VerifyGateMiddleware | None" = None  # 跨轮复用


SESSIONS: "OrderedDict[str, SessionState]" = OrderedDict()
_SESSIONS_LOCK = threading.Lock()  # 保护 SESSIONS 的并发读改(取用/插入/淘汰)


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
    return {"ok": True, "model": config.MINIMAX_MODEL, "key_configured": bool(config.MINIMAX_KEY)}


def _sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


async def _run_stream(
    goal: str,
    verify_cmd: str | None = None,
    project_dir: str | None = None,
    guard: list[str] | None = None,
) -> AsyncIterator[str]:
    """跑 agent,把每一步(模型决策/工具调用/工具结果/验证 bounce/升级求助/篡改警告/
    最终答案)作为 SSE 事件流出。verify_cmd 非空时挂 verify 硬门禁;project_dir 非空时
    在用户项目里干活并监控测试篡改。"""
    # 切运行时上下文:有 project_dir → 项目模式(用户项目);否则沙盒。
    if project_dir:
        runtime.use_project(project_dir)
        if guard:
            runtime.guard_files(guard)
    else:
        runtime.use_sandbox()
    try:
        # 传 goal → 结构化任务自动注入契约层约束(8→0 资产);非结构化不注入。
        agent, gate = build_agent_with_gate(verify_cmd=verify_cmd, goal=goal)
    except Exception as e:  # 配置缺失等
        yield _sse("error", {"message": str(e)})
        runtime.use_sandbox()
        return

    yield _sse("start", {"goal": goal})
    try:
        # astream 按 step 产出中间状态;每个 chunk 含新增的 messages。
        async for chunk in agent.astream({"messages": [("user", goal)]}, stream_mode="values"):
            msgs = chunk.get("messages", [])
            if not msgs:
                continue
            last = msgs[-1]
            kind = last.__class__.__name__
            calls = getattr(last, "tool_calls", None)
            content = str(last.content)
            if calls:
                yield _sse("tool_call", {"calls": [{"name": c["name"], "args": c["args"]} for c in calls]})
            elif kind == "ToolMessage":
                yield _sse("tool_result", {"content": content[:2000]})
            elif kind == "HumanMessage" and VerifyGateMiddleware.ESCALATION_TAG in content:
                # 门禁判定卡住 → 诚实升级,需人工指路。
                yield _sse("escalation", {"detail": content[:1500]})
            elif kind == "HumanMessage" and VerifyGateMiddleware.BOUNCE_TAG in content:
                # 门禁拦截了一次"假完成",把真实验证失败 bounce 回去。
                yield _sse("verify_failed", {"detail": content[:1500]})
            elif kind == "AIMessage":
                txt = final_text(last)
                if txt:
                    yield _sse("message", {"text": txt})
        # 篡改可见:project 模式下若 agent 动了被保护的测试文件,显著警告(诚实)。
        tampered = runtime.detect_tampering() if project_dir else []
        if tampered:
            yield _sse("tampering", {"files": tampered})
        # 收尾:若门禁标记 escalated,done 里带上诚实结论(供 UI 区分"真完成"vs"卡住了")。
        escalated = bool(gate and gate.escalated)
        # 沉淀任务记忆(真实、随任务生长)。verdict 诚实推断:
        #   有 verify_cmd 且未升级 → passed(真过了门禁);升级 → failed(诚实记失败);
        #   无 verify_cmd → none(不可验证,不假装通过)。
        verdict = ("failed" if escalated else "passed") if verify_cmd else None
        try:
            memory.record_task(goal=goal, verdict=verdict, model=config.MINIMAX_MODEL)
        except Exception:
            pass  # 记忆写入失败不该影响任务结果本身
        if escalated:
            yield _sse("done", {"resolved": False, "escalated": True, "attempts": gate.attempts, "tampered": tampered})
        else:
            yield _sse("done", {"resolved": True, "tampered": tampered})
    except Exception as e:
        yield _sse("error", {"message": str(e)})


@app.get("/memory")
def get_memory() -> dict:
    """Argos 自己跑过的任务记忆(真实、随任务生长)。前端据此构建记忆大脑图。
    没有记忆 → 空列表,前端显示诚实空态,而非编造假记忆。"""
    return {"records": memory.load_memories()}


@app.post("/run")
async def run(req: RunRequest) -> StreamingResponse:
    return StreamingResponse(
        _run_stream(req.goal, req.verify_cmd, req.project_dir, req.guard_files),
        media_type="text/event-stream",
    )
