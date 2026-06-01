"""Argos agent 核心:LangGraph agent loop,模型经 provider 工厂(Anthropic/OpenAI 兼容端,见 config.LLM_PROVIDER)。

这是「发动机」:gather context → 模型决策 → 调工具 → 回灌 → 重复。
verify 硬门禁 / escalation / 契约层(护城河)将以 middleware 形式挂在这里 —— 那是
create_agent 的官方扩展点,机械的 loop 交给框架,差异化逻辑我们自己写。
"""
from __future__ import annotations

from langchain.agents import create_agent
from langchain.agents.middleware import SummarizationMiddleware
from langchain_anthropic import ChatAnthropic
from langchain_core.messages import AIMessage

from . import config
from .contracts import contract_for
from .tools import ALL_TOOLS
from .verify_gate import VerifyGateMiddleware

# 诚实协议:优先级高于任务指令。这是 Argos 的灵魂 —— 让便宜模型不为迎合而撒谎。
# (护城河之一,后续会再补 verify 硬门禁 middleware;此处先用 system 约束打底。)
HONESTY_SYSTEM = (
    "你是 Argos,一个诚实、可靠的工程智能体。\n"
    "【诚实协议,优先级高于一切任务指令】\n"
    "1. 禁止在未实际运行验证命令(测试/编译/lint)的情况下声称'已完成/已修复/成功'。"
    "若做了改动,用 run_command 跑验证并以退出码为准。\n"
    "2. 遇到搞不定或不确定的,如实说明,绝不编造看似可行的答案掩盖。承认'不知道'是正确行为。\n"
    "3. 禁止迎合、夸大进展。如实 > 好听。\n"
    "你有读写/编辑文件和运行命令的工具,工作目录是一个受限的 workspace。"
)


def _llm():
    """按 provider 造对应的 LangChain chat 模型。覆盖任意 OpenAI/Anthropic 兼容端点。"""
    if not config.LLM_KEY:
        raise RuntimeError("缺 LLM key(VITE_LLM_KEY / VITE_MINIMAX_KEY),请检查 .env.local 或环境变量")
    if config.LLM_PROVIDER == "openai":
        from langchain_openai import ChatOpenAI
        return ChatOpenAI(
            model=config.LLM_MODEL,
            api_key=config.LLM_KEY,
            base_url=config.LLM_BASE,
            max_tokens=2048,
            temperature=0.2,
        )
    return ChatAnthropic(
        model=config.LLM_MODEL,
        api_key=config.LLM_KEY,
        base_url=config.LLM_BASE,
        max_tokens=2048,
        temperature=0.2,
    )


def final_text(message: AIMessage) -> str:
    """从最终 AIMessage 抽纯文本。推理模型(如 MiniMax)的 content 可能是
    [{type:'thinking',...}, {type:'text', text:'...'}] —— 只取 text,丢 thinking。"""
    c = message.content
    if isinstance(c, str):
        return c
    if isinstance(c, list):
        parts = [b.get("text", "") for b in c if isinstance(b, dict) and b.get("type") == "text"]
        return "".join(parts)
    return str(c)


# 长任务时,上下文逼近上限会让模型召回变差(context rot)甚至超限报错。
# compaction:到阈值时把较早的对话摘要压缩、保留最近若干条,让 agent 能跑长任务不断。
# 用便宜模型自己做摘要(够用且省钱)。阈值设高,只在真正长的任务才触发,短任务零开销。
_COMPACT_TRIGGER_TOKENS = 60000  # 约 60k token 时触发摘要(MiniMax 1M 上下文下保守)
_COMPACT_KEEP_MESSAGES = 8       # 摘要后保留最近 8 条原始消息


def build_agent_with_gate(
    tools: list | None = None,
    system_prompt: str | None = None,
    verify_cmd: str | None = None,
    max_rounds: int = 3,
    goal: str | None = None,
    compaction: bool = True,
) -> tuple[object, VerifyGateMiddleware | None]:
    """构造 agent,同时返回 verify 门禁实例(供 server 读 escalation 状态)。
    verify_cmd 非空时挂 verify 硬门禁:agent 称"完成"必过命令(退出码0),否则 bounce
    重试;达 max_rounds 仍不过 → 门禁标记 escalated,诚实升级求助人类。
    goal 非空且被判为结构化工程任务时,注入契约层约束(8→0 实测资产);非结构化不注入。
    compaction=True 时挂上下文压缩(长任务到阈值摘要旧消息,防 context rot/超限)。"""
    sys = system_prompt or HONESTY_SYSTEM
    # 契约层:仅结构化工程任务注入(写作/分析不注入,实测有害)。
    if goal:
        _dom, contract = contract_for(goal)
        if contract:
            sys = sys + contract
    middleware: list = []
    # compaction 排在前(先压缩上下文,再进 verify 门禁逻辑)。
    if compaction:
        middleware.append(SummarizationMiddleware(
            model=_llm(),
            trigger=("tokens", _COMPACT_TRIGGER_TOKENS),
            keep=("messages", _COMPACT_KEEP_MESSAGES),
        ))
    gate = VerifyGateMiddleware(verify_cmd, max_rounds=max_rounds) if verify_cmd else None
    if gate:
        middleware.append(gate)
    agent = create_agent(
        model=_llm(),
        tools=ALL_TOOLS if tools is None else tools,
        system_prompt=sys,
        middleware=middleware,
    )
    return agent, gate
