"""持续相关性修剪 —— context rot 三层防线的第二层(spec 2026-06-07)。

纯函数、**不依赖模型、不依赖 store**:作用在内存里要发给模型的 `messages` 列表上,
在触发整体压缩之前就一直做、优先于压缩。延续 `context/analyzer.py` 的"分桶"思路到
逐条消息——把低价值桶(过期工具输出 / 被取代的旧计划 / 死路错误)的**内容**折叠成短桩,
而**不可丢核心**(任务目标 + 最近 N 轮 + 当前 verify 命令)原样保留。

设计要点:
  · 折叠而非删除 —— 把消息 content 换成短桩,保留条数/顺序/角色交替,绝不破坏对话结构。
  · 优雅降级 —— 纯启发式(内容标记),不引模型;空/异常输入返回原样,绝不抛。
  · token 估算复用 `context/tokens.py`(与 analyzer 同一口径)。
"""
from __future__ import annotations

from dataclasses import dataclass

from argos_agent.context.tokens import token_estimate

# 折叠后的短桩(标注原因,人类/模型都能看出这里被修剪过)。
_STUB_TOOL = "[已修剪:过期工具输出]"
_STUB_PLAN = "[已修剪:被取代的旧计划]"
_STUB_DEAD = "[已修剪:走死路的探索]"

# 稳定内容标记(与 loop._feedback / _todos_summary / bounce 文案对齐)。
_TOOL_MARKERS = ("[执行结果]", "[执行完成", "[返回值]")
_DEAD_MARKERS = ("[执行异常]",)             # 工具执行报错 = 死路探索的痕迹
_PLAN_MARKER = "[Argos 任务清单"            # _todos_summary 锚


@dataclass(frozen=True, slots=True)
class CoreKeep:
    """不可丢核心定义:修剪/压缩都原样保留这部分。"""
    recent_turns: int = 6                  # 最近 N 条逐字保留
    verify_cmd: str | None = None          # 当前 verify 命令(含它的消息钉住不折叠)


@dataclass(frozen=True, slots=True)
class PruneResult:
    """修剪结果:新 messages 列表 + 折叠条数 + 回收的估算 token。"""
    messages: list[dict]
    removed: int                           # 本次折叠的消息条数
    removed_tokens: int                    # 折叠回收的估算 token(before - after)
    kept_core: int                         # 原样保留的核心条数


def _bucket(content: str) -> str:
    """把单条消息内容分到桶:tool_output / dead_end / plan / keep。"""
    c = (content or "").lstrip()
    if c.startswith(_PLAN_MARKER):
        return "plan"
    for m in _DEAD_MARKERS:
        if c.startswith(m):
            return "dead_end"
    for m in _TOOL_MARKERS:
        if c.startswith(m):
            return "tool_output"
    return "keep"


def _stub_for(bucket: str) -> str:
    return {"tool_output": _STUB_TOOL, "plan": _STUB_PLAN, "dead_end": _STUB_DEAD}[bucket]


def prune_messages(
    messages: list[dict],
    *,
    core: CoreKeep,
    aggressiveness: float = 0.5,
) -> PruneResult:
    """折叠中段低价值消息,核心原样保留。绝不抛(坏输入返回原样)。

    aggressiveness:
      · <= 0      不修剪(返回原样)
      · 0 < a<0.66 只折叠【过期工具输出】(tool_output)
      · >= 0.66   另折叠【被取代的旧计划】(只留最新一条任务清单) + 【死路错误】(dead_end)

    核心保护(永不折叠):
      · index 0(任务目标)
      · 最后 core.recent_turns 条
      · 含 verify_cmd 文本的消息
    """
    n = len(messages)
    if aggressiveness <= 0 or n == 0:
        return PruneResult(messages=list(messages), removed=0, removed_tokens=0, kept_core=n)

    recent = max(0, int(core.recent_turns))
    protected_tail_start = max(0, n - recent)
    fold_tool = aggressiveness > 0
    fold_more = aggressiveness >= 0.66

    # 被取代的旧计划:只保留【最后一条】任务清单,其余可折叠(fold_more 档生效)。
    last_plan_idx = -1
    for i, m in enumerate(messages):
        if _bucket(m.get("content") or "") == "plan":
            last_plan_idx = i

    out: list[dict] = []
    removed = 0
    removed_tokens = 0
    kept_core = 0
    for i, m in enumerate(messages):
        content = m.get("content") or ""
        is_core = (
            i == 0                                        # 任务目标
            or i >= protected_tail_start                  # 最近 N 条
            or (core.verify_cmd and core.verify_cmd in content)  # 当前 verify 命令
        )
        if is_core:
            kept_core += 1
            out.append(m)
            continue
        bucket = _bucket(content)
        do_fold = False
        if bucket == "tool_output" and fold_tool:
            do_fold = True
        elif bucket == "dead_end" and fold_more:
            do_fold = True
        elif bucket == "plan" and fold_more and i != last_plan_idx:
            do_fold = True
        if do_fold:
            stub = _stub_for(bucket)
            before, _ = token_estimate(content)
            after, _ = token_estimate(stub)
            removed += 1
            removed_tokens += max(0, before - after)
            out.append({**m, "content": stub})
        else:
            out.append(m)
    return PruneResult(
        messages=out, removed=removed, removed_tokens=removed_tokens, kept_core=kept_core,
    )
