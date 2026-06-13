"""best_of_n 1-task 自包含 demo(给真人/自己看核心故事用)。

不是 benchmark(不跑 TB 任务,不 docker,不统计 Δ)——只跑 1 个真 Python 任务,
N=1 和 N=k 各跑一遍,打平易近人的总结。

为啥要这个:
  - 跑 TB 完整 bench 4-6 task ≈ 30-80min,新人/外人不会一上来就干这个
  - best_of_n 是产品核心故事,需要一个 < 2min 的"看一眼就懂"demo
  - 不需要 docker/network,纯本地 python,任何配好 key 的人都能跑

用法:
  uv run python scripts/best_of_n_demo.py [--n 3]

任务:实现 fib(n) 满足 fib(10)==55。verify_cmd=python -c 真 import + assert。
子 agent 跑在 git worktree 隔离里(不污染主仓)。
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys
import time
from pathlib import Path

# 让脚本可以 import argos
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from argos import config
from argos.approval import ApprovalGate, ApprovalLevel
from argos.core.models import CredentialPool, ModelClient
from argos.core.verify_gate import Verifier
from argos.memory.store import ArgosStore
from argos.sandbox.broker import CapabilityBroker
from argos.sandbox.egress import EgressPolicy
from argos.tools.receipts import ReceiptSigner
from argos.workflow.engine import WorkflowEngine
from argos.workflow.spec import parse_spec
from argos.workflow.subagent import SubAgentFactory


# ── 自包含任务:写一个 fib(n) → verify 真实 import + assert ──
TASK_GOAL = (
    "在当前工作目录写一个 fib.py,实现 fib(n) 函数满足:\n"
    "  - fib(0) == 0, fib(1) == 1\n"
    "  - fib(n) = fib(n-1) + fib(n-2)  for n >= 2\n"
    "完成后 declare verify command: `python -c \"import sys; sys.path.insert(0,'.'); "
    "from fib import fib; assert fib(10) == 55; assert fib(0) == 0; assert fib(1) == 1\"`"
)
TASK_VERIFY_CMD = (
    "python -c \"import sys; sys.path.insert(0,'.'); "
    "from fib import fib; assert fib(10) == 55; assert fib(0) == 0; assert fib(1) == 1\""
)


def _build_components(workspace: Path):
    """从 active profile 构造 best_of_n 需要的全栈组件(sub_factory → engine)。
    无 worker key → 诚实在 stderr 抛 RuntimeError 退出 1,不假装能跑。

    workspace:git init 过的目录(best_of_n worktree 要 fork 它)。
    """
    tier = config.active_tier()
    key = config.active_key()
    if not key:
        raise RuntimeError(
            "未配置当前模型的 API key。请运行 `argos setup` 接入模型,"
            "或设置对应环境变量(见 `argos --help`)。Argos 不会假装能跑。"
        )
    pool = CredentialPool([key])
    model = ModelClient(tier=tier, pool=pool)
    gate = ApprovalGate(ApprovalLevel.AUTO)  # demo 全开 auto,不让审批弹窗阻
    egress = EgressPolicy(llm_hosts=set(), search_hosts=set(), mcp_hosts=set())
    signer = ReceiptSigner(key=os.urandom(32))
    broker = CapabilityBroker(gate=gate, egress=egress, signer=signer, workspace=workspace)

    def sub_model_factory(profile):
        # 不管 profile 填什么,统一用本脚本解析出来的模型(诚实:用户配的就是这个)
        return ModelClient(tier=tier, pool=CredentialPool([key]))

    sub_factory = SubAgentFactory(
        base_workspace=workspace, pool=pool, egress=egress, signer=signer,
        verifier=Verifier(max_rounds=2),
        store_factory=lambda: ArgosStore(db_path=":memory:"),
        model_factory=sub_model_factory,
    )
    engine = WorkflowEngine(sub_factory)
    return engine, model, tier


def _n_candidate_spec(*, n: int, model_tier: str) -> dict:
    """构造 1-stage best_of_n spec:同任务 N 个候选(独立 worktree),各自 verify。

    cap=1:单 key + 严 QPS 模型(agnes-flash / M3 实测)必须串行候选,并发 3 路必撞 429。
    多 key 用户可显式传 cap=N 走并行;demo 默认保守 = 1 拿稳结果。
    """
    return {
        "name": f"fib-demo-N{n}",
        "description": f"best_of_n 自包含 demo:写 fib(N={n}, model={model_tier}, cap=1 单 key 串行)",
        "stages": [{
            "id": "best",
            "op": "best_of_n",
            "n": n,
            "cap": 1,  # 单 key 串行;多 key 可改 cap=N 走并行
            "agent": {
                "prompt": TASK_GOAL,
                "tool_scope": "full",
                "isolation": "worktree",
                "verify": TASK_VERIFY_CMD,
                "role": "coder",
                "model": model_tier,
            },
        }],
    }


def _run_one_spec(engine: WorkflowEngine, spec_dict: dict) -> dict:
    """同步跑一个 best_of_n spec,返 winner 状态。winner.verdict='passed' → 真过了。"""
    spec = parse_spec(spec_dict)

    async def _go():
        async for _ev in engine.run(spec):
            pass  # 静默吞事件;真要给用户看流式进度再 yield
        assert engine.last_result is not None
        return engine.last_result

    result = asyncio.run(_go())
    assert result.stages, "best_of_n 必须有 1 个 stage"
    stage = result.stages[0]
    # best_of_n StageResult:results=(winner,), candidates=(全部 N 候选)
    winner = stage.results[0] if stage.results else None
    return {
        "winner_verdict": winner.verdict if winner else "failed",
        "winner_ok": winner.ok if winner else False,
        "winner_error": winner.error if winner else "no winner",
        "candidates": [
            {"agent_id": r.agent_id, "ok": r.ok, "verdict": r.verdict, "error": r.error}
            for r in stage.candidates
        ],
    }


def main() -> int:
    ap = argparse.ArgumentParser(
        description="best_of_n 1-task 自包含 demo(< 2min 看核心故事)",
    )
    ap.add_argument("--n", type=int, default=3,
                    help="best_of_n 候选数(N=1 是基线,另算;默认 3)")
    ap.add_argument("--workspace", type=Path, default=Path("/tmp/argos_best_of_n_demo"),
                    help="demo 工作目录(自动创建、git init)")
    args = ap.parse_args()

    base = args.workspace.expanduser().resolve()
    base.mkdir(parents=True, exist_ok=True)
    if not (base / ".git").exists():
        import subprocess
        subprocess.run(["git", "init", "-q", str(base)], check=True)
        subprocess.run(["git", "-C", str(base), "config", "user.email",
                        "demo@argos.local"], check=True)
        subprocess.run(["git", "-C", str(base), "config", "user.name",
                        "Argos Demo"], check=True)
        (base / ".gitignore").write_text(
            "bridge_base/\n"
            "__pycache__/\n"
            ".argos_run.sb\n"
            ".argos_sandbox.sb\n"
            ".argos_worktrees/\n",
            encoding="utf-8",
        )
        subprocess.run(["git", "-C", str(base), "add", ".gitignore"],
                       check=True, capture_output=True)
        subprocess.run(["git", "-C", str(base), "commit", "-q", "-m", "init"],
                       check=True, capture_output=True)

    print(f"[demo] model    = {config.active_tier().name} / {config.active_tier().model}")
    print(f"[demo] workspace = {base}")
    print(f"[demo] n        = {args.n}")
    print(f"[demo] task     = fib(n) 满足 fib(10)==55")
    print()

    try:
        engine, _model, tier = _build_components(base)
    except RuntimeError as e:
        print(f"[demo] {e}", file=sys.stderr)
        return 1

    # ── 跑 N=1 基线 ──
    print("=" * 60)
    print(f"[demo] 跑 N=1(单候选基线)...")
    t0 = time.time()
    n1 = _run_one_spec(engine, _n_candidate_spec(n=1, model_tier=tier.name))
    n1_elapsed = time.time() - t0
    n1_pass = n1["winner_verdict"] == "passed"
    n1c = n1["candidates"][0] if n1["candidates"] else {}
    print(f"[demo] N=1 状态: {'passed' if n1_pass else n1['winner_verdict']}  "
          f"(c0.verdict={n1c.get('verdict', '?')}, ok={n1c.get('ok', '?')}, "
          f"err={(n1c.get('error') or '-')[:200]})  ({n1_elapsed:.1f}s)")
    print()

    # ── 跑 N=k ──
    print("=" * 60)
    print(f"[demo] 跑 N={args.n}({args.n} 候选,选最好)...")
    t0 = time.time()
    nk = _run_one_spec(engine, _n_candidate_spec(n=args.n, model_tier=tier.name))
    nk_elapsed = time.time() - t0
    nk_pass = nk["winner_verdict"] == "passed"
    passed_n = sum(1 for c in nk["candidates"] if c.get("verdict") == "passed")
    for i, c in enumerate(nk["candidates"]):
        print(f"  c{i}: ok={c.get('ok', '?')} verdict={c.get('verdict', '?')} "
              f"err={(c.get('error') or '-')[:200]}")
    print(f"[demo] N={args.n} 状态: {'passed' if nk_pass else nk['winner_verdict']}  "
          f"({passed_n}/{args.n} 候选 passed)  ({nk_elapsed:.1f}s)")
    print()

    # ── 总结 ──
    print("=" * 60)
    print("[demo] 总结:")
    if n1_pass and nk_pass:
        verdict = "✓ N=1 和 N=k 都过了(任务太简单,看不出 N 价值 —— 试试更难的任务)"
    elif n1_pass and not nk_pass:
        verdict = "⚠ N=1 过了 N=k 没过(罕见,可能是 N=k 中没人收敛)"
    elif not n1_pass and nk_pass:
        verdict = "🎯 best_of_n 价值显现:N=1 单跑失败,N=k 中至少一个候选收敛并通过"
    else:
        verdict = "✗ N=1 和 N=k 都没过(任务可能太难 / 模型该换)"
    print(f"  {verdict}")
    print(f"  N=1   pass@1 = {'100%' if n1_pass else '0%'}")
    print(f"  N={args.n}   pass@1 = {'100%' if nk_pass else '0%'}")
    print(f"  Δ = {'+' if nk_pass and not n1_pass else '0'}pp(只 1 task,统计噪声大,真数据见 `scripts/tb_pass_at_1_benchmark.py` 跑 4-6 task)")
    print("=" * 60)
    return 0 if nk_pass else 1


if __name__ == "__main__":
    sys.exit(main())
