"""TB 适配器 + best_of_n 桥接 真跑 N=1 vs N=3 报告。

用法:
  uv run python scripts/tb_pass_at_1_benchmark.py [--n 3] [--workspace DIR]

读 ~/.argos/config.json 的 active profile 当 model;
跑 tests/eval/_fixtures/tb_smoke/ 下所有支持的 TB 任务(共 4 个);
N=1 与 N=k(=3)各跑一遍 best_of_n,打 N=1 / N=k pass@1 + supported/skipped 计数。

注:这是真跑(真沙箱 / 真 verify),不是 mock。
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

# 让脚本可以 import argos_agent(无需 pip install)
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from argos_agent import config
from argos_agent.approval import ApprovalGate, ApprovalLevel
from argos_agent.core.models import CredentialPool, ModelClient
from argos_agent.core.verify_gate import Verifier
from argos_agent.eval.benchmarks import terminal_bench_best_of_n as bridge
from argos_agent.sandbox.broker import CapabilityBroker
from argos_agent.sandbox.egress import EgressPolicy
from argos_agent.tools.receipts import ReceiptSigner
from argos_agent.workflow.engine import WorkflowEngine
from argos_agent.workflow.subagent import SubAgentFactory
from argos_agent.memory.store import ArgosStore


def _resolve_tier_and_key(use_env_override: bool) -> tuple:
    """解析(tier, key) — 默认走 active profile(用户在 ~/.argos/config.json 配的);
    --use-env-override 时优先 ARGOS_LLM_* / ANTHROPIC_* 环境变量。

    默认走 active 是更稳的:用户配好的模型(目前是 agnes-2.0-flash)是有 key 的,
    也一定可达;env override 在没显式传时反而会指向 M3(慢/卡)。新增显式 flag 让
    想用 env 的用户仍能 override。
    """
    if use_env_override:
        model = (os.environ.get("ARGOS_LLM_MODEL")
                 or os.environ.get("VITE_LLM_MODEL")
                 or os.environ.get("VITE_MINIMAX_MODEL")
                 or os.environ.get("ANTHROPIC_MODEL")
                 or os.environ.get("ANTHROPIC_DEFAULT_HAIKU_MODEL"))
        base = (os.environ.get("ARGOS_LLM_BASE")
                or os.environ.get("VITE_LLM_BASE")
                or os.environ.get("VITE_MINIMAX_URL")
                or os.environ.get("ANTHROPIC_BASE_URL"))
        key = (os.environ.get("ARGOS_LLM_KEY")
               or os.environ.get("VITE_LLM_KEY")
               or os.environ.get("VITE_MINIMAX_KEY")
               or os.environ.get("ANTHROPIC_AUTH_TOKEN"))
        provider = (os.environ.get("ARGOS_LLM_PROVIDER")
                    or os.environ.get("VITE_LLM_PROVIDER") or "anthropic").lower()
        if model and base and key:
            from argos_agent.core.models import ModelTier
            tier = ModelTier(
                name="script-override", model=model, base_url=base,
                max_tokens=8192, context_window=128000, protocol=provider,
            )
        return tier, key
    # 回退 active
    return config.active_tier(), config.active_key() or ""


def _build_components(workspace: Path, *, use_env_override: bool) -> dict:
    """拼一份真组件,仿 app_factory.build_components(本脚本不需要 TUI 装配)。"""
    tier, key = _resolve_tier_and_key(use_env_override)
    if not key:
        raise RuntimeError(
            "未配置任何可用 API key(ARGOS_LLM_KEY / VITE_MINIMAX_KEY / active profile key 皆空)。"
            "Argos 不会假装能跑。"
        )
    os.environ["ARGOS_WORKSPACE"] = str(workspace)
    workspace.mkdir(parents=True, exist_ok=True)
    # 把 workspace 初始化成 git repo + 一个初始 commit,让 git status 正常工作(否则
    # `git diff HEAD` 找不到 HEAD 而 fatal,我们的 output_mirror 退化为空)。
    # 同样:加 .gitignore 防 mirror 反馈(bridge 写 bridge_base/agent_workspace/...
    # 会被 agent 视为"新文件",下次 _mirror_worktree 再把它们拷进 next subagent 的 mirror,
    # 越拷越深)。
    import subprocess as _sp
    if not (workspace / ".git").is_dir():
        _sp.run(["git", "init", "-q", str(workspace)], check=False, capture_output=True)
        _sp.run(["git", "-C", str(workspace), "config", "user.email", "bench@local"], check=False, capture_output=True)
        _sp.run(["git", "-C", str(workspace), "config", "user.name", "bench"], check=False, capture_output=True)
        (workspace / ".gitignore").write_text(
            "bridge_base/\n"  # 唯一必须 ignore:防 mirror 反馈(详见 _mirror_worktree 注释)
            # 不 ignore 任何 .py/.sh/.txt —— agent 产出要进 mirror
            # 否则 _mirror_worktree 用 git status 看不到 → agent 工作白费
            "__pycache__/\n"
            ".argos_run.sb\n"
            ".argos_sandbox.sb\n"
            ".argos_worktrees/\n",
            encoding="utf-8",
        )
        _sp.run(["git", "-C", str(workspace), "add", ".gitignore"], check=False, capture_output=True)
        _sp.run(["git", "-C", str(workspace), "commit", "-q", "-m", "init"], check=False, capture_output=True)

    pool = CredentialPool([key])
    model = ModelClient(tier=tier, pool=pool)
    gate = ApprovalGate(ApprovalLevel.AUTO)  # 跑批量评测,关掉逐工具审批
    egress = EgressPolicy(
        llm_hosts={_host_of(tier.base_url)} if _host_of(tier.base_url) else set(),
        search_hosts=set(_SEARCH_HOSTS),
        mcp_hosts=set(),
    )
    signer = ReceiptSigner(key=os.urandom(32))
    broker = CapabilityBroker(gate=gate, egress=egress, signer=signer, workspace=workspace)

    def broker_handler(action, args):
        value, _exit = broker._execute(action, args)
        return value

    def sub_model_factory(profile):
        # 不管 profile 填什么,统一用本脚本解析出来的便宜模型(诚实:用户指定的就是这个)
        return ModelClient(tier=tier, pool=CredentialPool([key]))

    sub_factory = SubAgentFactory(
        base_workspace=workspace, pool=pool, egress=egress, signer=signer,
        verifier=Verifier(max_rounds=2),
        store_factory=lambda: ArgosStore(db_path=":memory:"),
        model_factory=sub_model_factory,
    )
    return {
        "sub_factory": sub_factory,
        "tier": tier,
        "model": model,
    }


def _host_of(base_url: str) -> str:
    from urllib.parse import urlparse
    p = urlparse(base_url)
    return p.hostname or ""


_SEARCH_HOSTS = ["duckduckgo.com", "tavily.com", "html.duckduckgo.com"]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=3, help="best_of_n 候选数(N=1 是基线,另算)")
    ap.add_argument("--workspace", type=Path, default=Path("/tmp/argos_tb_bench"))
    ap.add_argument("--smoke-dir", type=Path,
                    default=Path(__file__).resolve().parent.parent
                    / "tests" / "eval" / "_fixtures" / "tb_smoke",
                    help="TB fixture 根(默认仓库内置 smoke 集)")
    ap.add_argument("--tb-source", type=Path, default=None,
                    help="真 TB 任务根(如 /tmp/tb-inspect/original-tasks);给定时,"
                    "取其中真子目录,smoke-dir 忽略")
    ap.add_argument("--use-env-override", action="store_true",
                    help="用 ARGOS_LLM_* / ANTHROPIC_* 环境变量覆盖 active profile;"
                    "默认走 active(用户 ~/.argos/config.json 配的模型)")
    ap.add_argument("--only", type=str, default=None,
                    help="只跑指定 task 名(子目录名);省时间调试用")
    args = ap.parse_args()

    comps = _build_components(args.workspace, use_env_override=args.use_env_override)
    engine = WorkflowEngine(comps["sub_factory"])

    print(f"[bench] model = {comps['tier'].name} / {comps['tier'].model} @ {comps['tier'].base_url}")
    if args.tb_source:
        # 真 TB 路径:取 tb_source 下 6 个简单的子目录(hello-world + 类似,简单任务跑得
        # 快 + 模型容错高,适合拿稳多 task Δ 数据;任务越多越接近真实)。
        target_names = [
            "hello-world", "csv-to-parquet", "fix-permissions", "broken-python",
            "count-call-stack", "processing-pipeline",
        ]
        if args.only:
            target_names = [args.only]
        task_dirs = [args.tb_source / n for n in target_names if (args.tb_source / n).is_dir()]
        print(f"[bench] tb source = {args.tb_source} (only={args.only})")
    else:
        print(f"[bench] smoke dir = {args.smoke_dir}")
        task_dirs = sorted(p for p in args.smoke_dir.iterdir() if p.is_dir())
    print(f"[bench] workspace = {args.workspace}")
    print(f"[bench] n = {args.n}")

    t0 = time.time()
    report = bridge.run_pass_at_1(
        task_dirs, engine=engine, n=args.n,
        base_dir=args.workspace / "bridge_base", persist=False,
    )
    dt = time.time() - t0

    print()
    print("=" * 60)
    print(f"[bench] total_seen = {report.total_seen}")
    print(f"[bench] supported  = {report.supported}")
    print(f"[bench] skipped    = {report.skipped}")
    if report.unsupported_reasons:
        for k, n in report.unsupported_reasons.items():
            print(f"[bench]   skip reason: {k} × {n}")
    print()
    print(f"[bench] pass@1 (N=1) = {report.pass_at_1_n1 * 100:.1f}%")
    print(f"[bench] pass@1 (N={args.n}) = {report.pass_at_1_n3 * 100:.1f}%")
    delta = report.pass_at_1_n3 - report.pass_at_1_n1
    print(f"[bench] Δ  = {delta * 100:+.1f}pp")
    print()
    print("[bench] per-task status:")
    for tid, (status, reason) in report.per_task_status.items():
        line = f"  {tid:<24}  {status}"
        if status == "skipped":
            line += f"  — {reason}"
        elif reason:
            line += f"  ({reason})"
        print(line)
    print()
    print(f"[bench] elapsed = {dt:.1f}s")
    print("=" * 60)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
