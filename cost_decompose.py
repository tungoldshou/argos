"""拆解 29x token —— 把成本分成三层,得到诚实的"verify 净代价"。

成本基线表的 29x 是"裸 chat 一次 vs 完整 agent 闭环"的对比,把三样东西混在一起:
  ① agent 框架固定开销:thinking + 工具往返(写文件等),便宜的推理模型每步都有
  ② verify 门禁本身:跑验证命令(便宜,确定性)
  ③ verify 触发的重试:失败→bounce→重生成(真正的"为可靠性多花的钱")

只有 ②③ 是"为 verify 多花的",① 是"用 agent 而非裸 chat"的固定成本,不该算到 verify 头上。

做法:同一个【一次就能做对】的任务,跑两条 agent(都带工具/thinking,公平):
  A. 无 verify gate(裸 agent):成本 = ①
  B. 有 verify gate 但任务一次过(不触发重试):成本 = ① + ②
  → B−A = verify 门禁固定开销 ②(应该很小,就是跑一次命令)
再对比"裸 chat 一次"得到 agent 框架相对 chat 的放大,以及闭环里重试 ③ 的占比。

跑:uv run python cost_decompose.py
"""
from __future__ import annotations

from langchain_anthropic import ChatAnthropic

from argos_agent import config
from argos_agent.core import build_agent_with_gate, final_text
from argos_agent.tools import VERIFY_DIR, WORKSPACE
from argos_agent.verify_gate import _run_verify


def _tokens_of(messages) -> int:
    total = 0
    for m in messages:
        u = getattr(m, "usage_metadata", None)
        if u:
            total += u.get("input_tokens", 0) + u.get("output_tokens", 0)
    return total


# 一个【便宜模型基本能一次做对】的简单任务(让 B 不触发重试,纯测门禁固定开销)。
TASK = ("在 workspace 写 easy_sol.py,export 一个函数 inc(n: int) -> int 返回 n+1。说完成。")
CHECK = "from easy_sol import inc\nassert inc(1)==2\nassert inc(0)==1\nprint('PASS')\n"


def main() -> None:
    print(f"\n模型: {config.MINIMAX_MODEL}  |  拆解 verify 成本\n")
    VERIFY_DIR.mkdir(parents=True, exist_ok=True)
    WORKSPACE.mkdir(parents=True, exist_ok=True)
    (VERIFY_DIR / "easy_check.py").write_text(CHECK, encoding="utf-8")

    # 基准0:裸 chat 一次(无 agent,无工具)。
    llm = ChatAnthropic(model=config.MINIMAX_MODEL, api_key=config.MINIMAX_KEY,
                        base_url=config.MINIMAX_BASE, max_tokens=1024, temperature=0.2)
    r0 = llm.invoke([("user", "写一个 python 函数 inc(n) 返回 n+1,只输出代码。")])
    u0 = r0.usage_metadata or {}
    chat_tok = u0.get("input_tokens", 0) + u0.get("output_tokens", 0)

    # A:裸 agent(无 verify gate),带工具/thinking。成本 = ① agent 框架固定开销。
    (WORKSPACE / "easy_sol.py").unlink(missing_ok=True)
    agA, _ = build_agent_with_gate(verify_cmd=None)
    rA = agA.invoke({"messages": [("user", TASK)]})
    tokA = _tokens_of(rA["messages"])

    # B:带 verify gate,但任务一次过(不触发重试)。成本 = ① + ② 门禁固定开销。
    (WORKSPACE / "easy_sol.py").unlink(missing_ok=True)
    agB, gateB = build_agent_with_gate(verify_cmd="python3 easy_check.py", max_rounds=3)
    rB = agB.invoke({"messages": [("user", TASK)]})
    tokB = _tokens_of(rB["messages"])
    b_retried = gateB.escalated or False  # 简化:理想下 B 不该重试

    print("=" * 56)
    print("verify 成本拆解")
    print("=" * 56)
    print(f"① 裸 chat 一次(无agent)         : {chat_tok:>8} token")
    print(f"② 裸 agent(工具+thinking,无verify): {tokA:>8} token   ← agent 框架固定开销")
    print(f"③ agent+verify(一次过,不重试)    : {tokB:>8} token")
    print("-" * 56)
    print(f"agent 框架放大(②/①)             : {tokA/max(chat_tok,1):>7.1f}x  ← 用 agent 而非裸chat 的代价")
    print(f"verify 门禁净开销(③−②)           : {tokB-tokA:>8} token ({(tokB-tokA)/max(tokA,1)*100:.0f}% of agent)")
    print(f"B 是否触发了重试                  : {'是(此任务没想象简单)' if b_retried else '否(纯门禁开销)'}")
    print("=" * 56)
    print("\n判读:")
    print(" · 若'agent 框架放大'是大头 → 29x 主要是'用 agent 不用裸chat'的代价,不是 verify 的锅。")
    print(" · 若'verify 门禁净开销'很小 → 跑验证本身几乎不花钱,贵的是失败重试(只在难任务发生)。")
    print(" · 真正'为可靠性多花的钱' = 重试成本,只在便宜模型做错时才付,做对的任务零额外。\n")


if __name__ == "__main__":
    main()
