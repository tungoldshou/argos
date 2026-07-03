"""Internal documentation."""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from argos import config
from argos.approval import ApprovalGate, ApprovalLevel
from argos.core.models import CredentialPool, ModelClient
from argos.core.verify_gate import Verifier
from argos.eval.benchmarks import terminal_bench_best_of_n as bridge
from argos.sandbox.broker import CapabilityBroker
from argos.sandbox.egress import EgressPolicy
from argos.tools.receipts import ReceiptSigner
from argos.workflow.engine import WorkflowEngine
from argos.workflow.subagent import SubAgentFactory
from argos.memory.store import ArgosStore


def _resolve_tier_and_key(use_env_override: bool) -> tuple:
    """Internal documentation."""
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
            from argos.core.models import ModelTier
            tier = ModelTier(
                name="script-override", model=model, base_url=base,
                max_tokens=8192, context_window=128000, protocol=provider,
            )
        return tier, key
    return config.active_tier(), config.active_key() or ""


def _build_components(workspace: Path, *, use_env_override: bool) -> dict:
    """Internal documentation."""
    tier, key = _resolve_tier_and_key(use_env_override)
    if not key:
        raise RuntimeError(
            "未配置任何可用 API key(ARGOS_LLM_KEY / VITE_MINIMAX_KEY / active profile key 皆空)。"
            "Argos 不会假装能跑。"
        )
    os.environ["ARGOS_WORKSPACE"] = str(workspace)
    workspace.mkdir(parents=True, exist_ok=True)
    import subprocess as _sp
    if not (workspace / ".git").is_dir():
        _sp.run(["git", "init", "-q", str(workspace)], check=False, capture_output=True)
        _sp.run(["git", "-C", str(workspace), "config", "user.email", "bench@local"], check=False, capture_output=True)
        _sp.run(["git", "-C", str(workspace), "config", "user.name", "bench"], check=False, capture_output=True)
        (workspace / ".gitignore").write_text(
            "bridge_base/\n"
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
    gate = ApprovalGate(ApprovalLevel.AUTO)
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
