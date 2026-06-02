"""planner 拆活 —— M3 强模型 + 剥 <think> 块 + lenient JSON 提取(探针已证)。

策略:不依赖 response_format=json_object(OpenAI-compat 端点不可靠),而是在解析端兜型。
pydantic PlanSpec 兜住任何错型 → 抛 PlannerError,不让坏 JSON 流到 worker(spec §4.3 红线)。

M3 不可用(缺 key)→ _llm 抛 RuntimeError → planner_llm 捕住转 PlannerError → orchestrator escalate。
"""
from __future__ import annotations

import json
import re
from typing import Any

from . import core
from .plan_schema import PlanSpec, PlannerError, PlanTask

# M3 是推理模型,默认带 <think>...</think> 块。探针:response_format=json_object 不工作,
# 必须先剥 thinking 块再 lenient 提取。
_THINK_RE = re.compile(r"<think>.*?</think>", re.DOTALL)

# 任务数硬上限(spec §5 范围 2-5)
MAX_TASKS = 5
MIN_TASKS = 2


def _chat(messages: list[dict], model: str, temperature: float, max_tokens: int) -> Any:
    """一个独立的 chat 入口,便于测试 monkeypatch。生产:调 _llm(tier="planner") 构造的 chat 模型。"""
    from langchain_core.messages import HumanMessage, SystemMessage
    lc_msgs = []
    for m in messages:
        if m["role"] == "system":
            lc_msgs.append(SystemMessage(content=m["content"]))
        else:
            lc_msgs.append(HumanMessage(content=m["content"]))
    chat = core._llm(tier="planner")
    r = chat.invoke(lc_msgs)
    # 推理模型(如 M3)的 content 可能是 [{type:'thinking',...},{type:'text',text:'...'}] 列表,
    # 用 core.final_text 抽纯 text(与 server.py text_delta 同源策略)。
    content = core.final_text(r) if hasattr(r, "content") else str(r)
    return _FakeChoice(content)


class _FakeChoice:
    """包成与 OpenAI SDK 类似的 shape,便于测试 mock 注入。"""
    def __init__(self, content): self.message = type("M", (), {"content": content})()


def _strip_think(txt: str) -> str:
    return _THINK_RE.sub("", txt).strip()


def _extract_json(txt: str) -> str:
    """找第一 { 到最后 } 的子串。容忍前后有 markdown fence / 解释。"""
    s = txt.find("{")
    e = txt.rfind("}")
    if s < 0 or e <= s:
        raise PlannerError(f"no JSON object found in planner output: {txt[:200]!r}")
    return txt[s:e + 1]


def _truncate_tasks(parsed: dict) -> dict:
    """超 MAX_TASKS 截断(spec §5 范围 2-5)。不足 MIN_TASKS 由 pydantic 兜型拒。"""
    tasks = parsed.get("tasks", [])
    if not isinstance(tasks, list):
        raise PlannerError(f"tasks field not a list: {type(tasks).__name__}")
    if len(tasks) > MAX_TASKS:
        parsed["tasks"] = tasks[:MAX_TASKS]
    return parsed


def planner_llm(goal: str) -> PlanSpec:
    """调 M3 强模型拆活 → 剥 thinking 块 → lenient JSON 提取 → pydantic 兜型。"""
    messages = [
        {"role": "system", "content": (
            "你是工程任务规划器。把用户给的批量工程任务拆成 2-5 个可独立验证的子任务。"
            "每条子任务含 goal(具体到能直接由 agent 执行)+ verify_cmd(完成后跑哪条命令验证)。"
        )},
        {"role": "user", "content": (
            f"任务:{goal}\n\n"
            "只输出一个 JSON 对象,严格如下形状(可包含 <think> 思考块,最终必须含纯 JSON):\n"
            '{"tasks": [{"goal": "...", "verify_cmd": "..."}, ...]}'
        )},
    ]
    try:
        choice = _chat(messages, model=core.config.LLM_MODEL, temperature=0.2, max_tokens=800)
    except RuntimeError as e:
        # _llm 缺 key 抛 RuntimeError → 显式 PlannerError,orchestrator 据此 escalate(不降级 M2)
        raise PlannerError(f"planner LLM unavailable: {e!r}") from e
    txt = choice.message.content
    stripped = _strip_think(txt or "")
    try:
        parsed = json.loads(_extract_json(stripped))
    except (json.JSONDecodeError, PlannerError) as e:
        raise PlannerError(f"planner output not valid JSON: {e!r}; raw={txt[:300]!r}") from e
    parsed = _truncate_tasks(parsed)
    try:
        return PlanSpec.model_validate(parsed)
    except Exception as e:
        raise PlannerError(f"PlanSpec validation failed: {e!r}") from e
