"""成本基线生死表 —— 回答悬最久的存亡问题:
    便宜模型 + Argos verify 闭环,比【便宜模型裸调】交付率高多少?多花多少 token?

这是决定整个方向值不值得的那张账表(对抗审查的存亡问题2)。用退出码当 ground truth,
不靠模型自评。隔离区放隐藏测试,agent 改不到(防作弊)。

跑:uv run python cost_ab.py
"""
from __future__ import annotations

import time
from pathlib import Path

from langchain_anthropic import ChatAnthropic

from argos_agent import config
from argos_agent.core import build_agent_with_gate, final_text
from argos_agent.tools import VERIFY_DIR, WORKSPACE
from argos_agent.verify_gate import _run_verify

# ── token 计量(累计 in/out)──────────────────────────────────────────────────
_usage = {"bare_in": 0, "bare_out": 0, "loop_in": 0, "loop_out": 0}


def _bare_llm() -> ChatAnthropic:
    return ChatAnthropic(
        model=config.MINIMAX_MODEL, api_key=config.MINIMAX_KEY,
        base_url=config.MINIMAX_BASE, max_tokens=2048, temperature=0.2,
    )


# ── 任务集:结构化、退出码可判、隐藏测试放隔离区 ────────────────────────────────
TASKS = [
    {
        "name": "parse_duration",
        "module": "pd_sol",
        "prompt": ("在 workspace 写 pd_sol.py,export 一个函数 parse_duration(s: str) -> int,"
                   "把人类时长解析成毫秒:支持组合如 '1h30m'→5400000,'500ms'→500,'2d'→172800000,"
                   "'90s'→90000,'1h'→3600000。单位 ms/s/m/h/d。非法输入(空串/未知单位/纯数字)抛 ValueError。"
                   "写完说完成。"),
        "check": ("from pd_sol import parse_duration as f\n"
                  "assert f('500ms')==500\nassert f('90s')==90000\nassert f('1h')==3600000\n"
                  "assert f('1h30m')==5400000\nassert f('2d')==172800000\n"
                  "for bad in ['10x','','123']:\n"
                  "    try:\n        f(bad); raise SystemExit('should raise '+bad)\n    except ValueError: pass\n"
                  "print('PASS')\n"),
    },
    {
        "name": "paginate",
        "module": "pg_sol",
        "prompt": ("在 workspace 写 pg_sol.py,export 函数 paginate(items, page, size) 返回 dict "
                   "{'data':..., 'total':..., 'page':..., 'pages':...}。page 从1开始;size<1当作1;"
                   "page 超界则 data 空但 total/pages 正确;pages=ceil(total/size),空列表时 pages=0。说完成。"),
        "check": ("from pg_sol import paginate as f\nimport json\n"
                  "J=lambda x:json.dumps(x,sort_keys=True)\na=[1,2,3,4,5]\n"
                  "assert J(f(a,1,2))==J({'data':[1,2],'total':5,'page':1,'pages':3})\n"
                  "assert J(f(a,3,2))==J({'data':[5],'total':5,'page':3,'pages':3})\n"
                  "assert J(f(a,9,2))==J({'data':[],'total':5,'page':9,'pages':3})\n"
                  "assert J(f([],1,10))==J({'data':[],'total':0,'page':1,'pages':0})\n"
                  "print('PASS')\n"),
    },
    {
        "name": "slugify",
        "module": "sl_sol",
        "prompt": ("在 workspace 写 sl_sol.py,export 函数 slugify(s: str) -> str:小写,空格和下划线转连字符,"
                   "去掉非字母数字和连字符的字符,多个连字符合并成一个,首尾连字符去掉。说完成。"),
        "check": ("from sl_sol import slugify as f\n"
                  "assert f('Hello World')=='hello-world', f('Hello World')\n"
                  "assert f('  Foo__Bar  ')=='foo-bar', f('  Foo__Bar  ')\n"
                  "assert f('a!!!b')=='ab', f('a!!!b')\n"
                  "assert f('--x--y--')=='x-y', f('--x--y--')\n"
                  "print('PASS')\n"),
    },
]


def run_bare(task: dict) -> bool:
    """裸调:模型直接产出,写文件,跑一次验证。不重试。返回是否一次过。"""
    llm = _bare_llm()
    resp = llm.invoke([("system", "你是工程师,只输出完整可运行代码。"), ("user", task["prompt"])])
    u = resp.usage_metadata or {}
    _usage["bare_in"] += u.get("input_tokens", 0)
    _usage["bare_out"] += u.get("output_tokens", 0)
    # 抠代码写进 workspace(裸调不走 agent 工具,我们替它落盘以公平对比验证)。
    text = final_text(resp) if hasattr(resp, "content") else str(resp.content)
    code = _extract_code(text)
    (WORKSPACE / f"{task['module']}.py").write_text(code, encoding="utf-8")
    ok, _ = _run_verify(f"python3 {task['name']}_check.py")
    return ok


def run_loop(task: dict) -> tuple[bool, int]:
    """Argos 闭环:agent + verify 硬门禁。返回 (是否交付, 估算调用轮数)。"""
    agent, gate = build_agent_with_gate(verify_cmd=f"python3 {task['name']}_check.py", max_rounds=3)
    r = agent.invoke({"messages": [("user", task["prompt"])]})
    # 累计 token:遍历消息里的 usage_metadata。
    rounds = 0
    for m in r["messages"]:
        u = getattr(m, "usage_metadata", None)
        if u:
            _usage["loop_in"] += u.get("input_tokens", 0)
            _usage["loop_out"] += u.get("output_tokens", 0)
            rounds += 1
    delivered = not gate.escalated and _run_verify(f"python3 {task['name']}_check.py")[0]
    return delivered, rounds


def _extract_code(text: str) -> str:
    import re
    m = re.search(r"```(?:python|py)?\s*\n([\s\S]*?)```", text)
    return (m.group(1) if m else text).strip()


def _setup_checks() -> None:
    """把隐藏测试写进隔离区(agent 够不到)。"""
    VERIFY_DIR.mkdir(parents=True, exist_ok=True)
    WORKSPACE.mkdir(parents=True, exist_ok=True)
    for t in TASKS:
        (VERIFY_DIR / f"{t['name']}_check.py").write_text(t["check"], encoding="utf-8")


def main() -> None:
    print(f"\n模型: {config.MINIMAX_MODEL}  |  {len(TASKS)} 个结构化任务\n")
    _setup_checks()
    bare_ok = loop_ok = 0
    t0 = time.time()
    for t in TASKS:
        # 清掉上轮产物,保证每个 arm 从零开始。
        (WORKSPACE / f"{t['module']}.py").unlink(missing_ok=True)
        b = run_bare(t)
        bare_ok += b
        (WORKSPACE / f"{t['module']}.py").unlink(missing_ok=True)
        d, _ = run_loop(t)
        loop_ok += d
        print(f"[{t['name']}] 裸调={'过' if b else '挂'}  Argos闭环={'交付' if d else '未交付'}")
    wall = time.time() - t0

    n = len(TASKS)
    bt = _usage["bare_in"] + _usage["bare_out"]
    lt = _usage["loop_in"] + _usage["loop_out"]
    print("\n" + "=" * 56)
    print("成本基线生死表")
    print("=" * 56)
    print(f"裸调一次过率      : {bare_ok}/{n}  ({bare_ok/n*100:.0f}%)   token {bt}")
    print(f"Argos闭环交付率   : {loop_ok}/{n}  ({loop_ok/n*100:.0f}%)   token {lt}")
    print(f"可靠性提升        : +{(loop_ok-bare_ok)/n*100:.0f} 个百分点")
    print(f"token 倍数        : {lt/max(bt,1):.1f}x (闭环/裸调)")
    print(f"墙钟              : {wall:.0f}s")
    print("=" * 56)
    print("\n判读:可靠性提升够大 且 token 倍数可接受 → 划算,方向成立。")
    print("     若提升小或 token 暴涨 → 便宜+verify 不如直接用强模型。\n")


if __name__ == "__main__":
    main()
