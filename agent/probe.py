"""第一层验证:LangGraph + ChatAnthropic 能否调通 MiniMax(Anthropic 兼容端)。
脱离 Tauri/FastAPI,纯命令行先证明 Python agent 内核能跑。"""
import os
import sys
import time
from pathlib import Path

from langchain_anthropic import ChatAnthropic
from langchain_core.tools import tool
from langgraph.prebuilt import create_react_agent


def load_key() -> tuple[str, str]:
    """从仓库根的 .env.local 读 MiniMax key/model(与前端共用一份配置)。"""
    env = {}
    envfile = Path(__file__).resolve().parent.parent / ".env.local"
    for line in envfile.read_text().splitlines():
        line = line.strip()
        if "=" in line and not line.startswith("#"):
            k, v = line.split("=", 1)
            env[k.strip()] = v.strip()
    key = env.get("VITE_MINIMAX_KEY")
    model = env.get("VITE_MINIMAX_MODEL", "MiniMax-M2")
    if not key:
        sys.exit("缺 VITE_MINIMAX_KEY")
    return key, model


@tool
def get_word_length(word: str) -> int:
    """返回一个单词的字母数。"""
    return len(word)


def main() -> None:
    key, model = load_key()
    print(f"model: {model}")

    # ChatAnthropic 指向 MiniMax 的 Anthropic 兼容端。base_url 到 /anthropic 那层,
    # langchain-anthropic 自己拼 /v1/messages。
    llm = ChatAnthropic(
        model=model,
        api_key=key,
        base_url="https://api.minimaxi.com/anthropic",
        max_tokens=1024,
        temperature=0.2,
    )

    agent = create_react_agent(llm, tools=[get_word_length])

    t0 = time.time()
    result = agent.invoke(
        {"messages": [("user", "单词 'strawberry' 有几个字母?用工具数,然后只回数字。")]}
    )
    dt = time.time() - t0

    msgs = result["messages"]
    print(f"=== 共 {len(msgs)} 条消息, 耗时 {dt:.1f}s ===")
    for m in msgs:
        kind = m.__class__.__name__
        # tool 调用 / tool 结果 / 文本,分别打印,确认 ReAct loop 真转起来了
        calls = getattr(m, "tool_calls", None)
        if calls:
            print(f"[{kind}] tool_calls: {[(c['name'], c['args']) for c in calls]}")
        content = m.content if isinstance(m.content, str) else str(m.content)
        if content.strip():
            print(f"[{kind}] {content[:200]}")
    print("\n=== FINAL:", msgs[-1].content)


if __name__ == "__main__":
    main()
