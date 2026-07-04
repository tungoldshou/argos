from __future__ import annotations

import os
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from argos.approval import ApprovalGate, ApprovalLevel
from argos.i18n import t
from argos.core.loop import AgentLoop, LoopConfig
from argos.sandbox.broker import CapabilityBroker
from argos.sandbox.executor import select_backend
from argos.protocol.events import Error, PhaseChange, TokenDelta, VerifyVerdict
from argos.protocol.events import EventBus
from argos.workflow.result import AgentResult
from argos.workflow.spec import AgentTask, ROLE_PRESETS
from argos.workflow.worktree import worktree_for

OnPhase = Callable[[str, str, str], None]

_DEFAULT_MAX_STEPS = 20


def _resolve_role(task: AgentTask):
    if task.role is None:
        return None
    return ROLE_PRESETS.get(task.role)


@dataclass(frozen=True, slots=True)
class SubAgentFactory:

    base_workspace: Path
    pool: Any
    egress: Any
    signer: Any
    verifier: Any
    store_factory: Callable[[], Any]
    model_factory: Callable[[str | None], Any]
    inline_diff: bool = False
    output_mirror: Path | None = None

    async def run_task(
        self,
        task: AgentTask,
        *,
        item: object,
        agent_id: str,
        on_phase: OnPhase,
    ) -> AgentResult:
        try:
            return await self._run(task, item=item, agent_id=agent_id, on_phase=on_phase)
        except Exception as e:  # noqa: BLE001
            return AgentResult(
                agent_id=agent_id, ok=False, output="",
                error=f"{type(e).__name__}: {e}",
            )

    async def _run(
        self,
        task: AgentTask,
        *,
        item: object,
        agent_id: str,
        on_phase: OnPhase,
    ) -> AgentResult:
        prompt = task.prompt.replace("{item}", str(item)) if item is not None else task.prompt
        role_preset = _resolve_role(task)
        if role_preset is not None:
            derived_read_only = role_preset.read_only
            derived_allowlist: "list[str] | None" = list(role_preset.tool_allowlist)
            max_steps = role_preset.max_steps
            prompt = t("wf.subagent.role_prefix", role_name=role_preset.name) + f"\n{role_preset.system_prompt}\n\n---\n\n{prompt}"
        else:
            derived_read_only = (task.tool_scope == "read")
            derived_allowlist = None
            max_steps = _DEFAULT_MAX_STEPS
        model = self.model_factory(task.model)
        gate = ApprovalGate(ApprovalLevel.AUTO)

        report_parts: list[str] = []
        verdict_status: str | None = None
        early_error: str | None = None
        tokens_in = 0
        tokens_out = 0

        with worktree_for(self.base_workspace, agent_id, task.isolation) as (workdir, note):
            broker = CapabilityBroker(
                gate=gate, egress=self.egress, signer=self.signer, workspace=workdir,
            )

            def _bridge(action: str, args: dict) -> object:
                value, _exit = broker.execute_sync(action, args)
                return value

            sandbox_cls = select_backend()
            sandbox = sandbox_cls(broker_handler=_bridge)
            cfg = LoopConfig(
                model_tier=model.tier.name,
                verify_cmd=task.verify,
                max_rounds=2,
                max_steps=max_steps,
                compaction=True,
                approval_level=ApprovalLevel.AUTO,
            )
            from argos.memory.auto import project_id_for as _pid
            loop = AgentLoop(
                store=self.store_factory(),
                bus=EventBus(),
                sandbox=sandbox,
                broker=broker,
                model=model,
                verifier=self.verifier,
                config=cfg,
                workspace=workdir,
                verify_dir=workdir,
                project_id=_pid(self.base_workspace),
                allow_workflow=False,
                read_only=derived_read_only,
                tool_allowlist=derived_allowlist,
            )
            try:
                async for ev in loop.run(prompt, session_id=agent_id):
                    if isinstance(ev, TokenDelta):
                        report_parts.append(ev.text)
                    elif isinstance(ev, PhaseChange):
                        on_phase(agent_id, ev.phase, "")
                    elif isinstance(ev, VerifyVerdict):
                        verdict_status = ev.verdict.status
                    elif isinstance(ev, Error):
                        early_error = ev.message
                        break
            finally:
                sandbox.close()
                usage = getattr(model, "last_usage", {}) or {}
                tokens_in = int(usage.get("input_tokens") or 0)
                tokens_out = int(usage.get("output_tokens") or 0)

            if early_error is not None:
                return AgentResult(
                    agent_id=agent_id, ok=False, output="", error=early_error,
                    tokens_in=tokens_in, tokens_out=tokens_out,
                )

            output = "".join(report_parts).strip()
            if note:
                output = output + t("wf.subagent.isolation_note", note=note)

            diff_text: str | None = None
            diff_ref: str | None = None
            diff_summary: str | None = None
            diff_file_count: int = 0
            if workdir != self.base_workspace:
                diff_text = self._capture_diff_text(workdir)
                if diff_text:
                    if self.inline_diff:
                        output += t("wf.subagent.diff_inline_header") + diff_text
                    else:
                        diff_ref = self._persist_diff_journal(agent_id, diff_text)
                        diff_summary, diff_file_count = self._summarize_diff(diff_text)
                        if diff_summary:
                            output += t("wf.subagent.diff_summary_prefix", summary=diff_summary)
                        if diff_ref:
                            output += t("wf.subagent.diff_ref_prefix", ref=diff_ref)

            if self.output_mirror is not None:
                try:
                    self.output_mirror.mkdir(parents=True, exist_ok=True)
                    self._mirror_worktree(workdir, self.output_mirror)
                except Exception as e:  # noqa: BLE001
                    log.warning("[subagent] output_mirror 失败 %s: %s", agent_id, e)

            return AgentResult(
                agent_id=agent_id, ok=True, output=output, verdict=verdict_status,
                tokens_in=tokens_in, tokens_out=tokens_out,
                diff_ref=diff_ref, diff_summary=diff_summary,
                diff_file_count=diff_file_count,
            )

    @staticmethod
    def _capture_diff_text(workdir: Path) -> str | None:
        import subprocess
        try:
            subprocess.run(["git", "-C", str(workdir), "add", "-A"],
                           capture_output=True, timeout=10)
            r = subprocess.run(
                ["git", "-C", str(workdir), "diff", "--cached"],
                capture_output=True, text=True, timeout=10,
            )
            diff = r.stdout or ""
            return diff if diff.strip() else None
        except Exception:  # noqa: BLE001
            return None

    @staticmethod
    def _summarize_diff(diff_text: str) -> tuple[str, int]:
        import re
        files = re.findall(r"^diff --git a/", diff_text, flags=re.MULTILINE)
        n = len(files)
        if n == 0:
            return ("", 0)
        added = 0
        removed = 0
        for m in re.finditer(r"^@@ -\d+(?:,(\d+))? \+\d+(?:,(\d+))? @@", diff_text,
                              flags=re.MULTILINE):
            removed += int(m.group(1) or "1")
            added += int(m.group(2) or "1")
        return (f"{n} files changed, +{added}/-{removed} lines", n)

    @staticmethod
    def _mirror_worktree(src: Path, dst: Path) -> None:
        import shutil
        import subprocess

        try:
            r = subprocess.run(
                ["git", "-C", str(src), "status", "--porcelain", "--untracked-files=all"],
                capture_output=True, text=True, timeout=10,
            )
        except (subprocess.TimeoutExpired, FileNotFoundError):
            shutil.copytree(src, dst, dirs_exist_ok=True, ignore=shutil.ignore_patterns(".git"))
            return

        files: set[str] = set()
        for line in (r.stdout or "").splitlines():
            line = line.rstrip()
            if not line:
                continue
            if len(line) < 4:
                continue
            status = line[:2]
            path = line[3:]
            if " -> " in path:
                path = path.split(" -> ", 1)[1]
            if path.startswith(".git") or "/.git/" in path:
                continue
            if status.strip() in ("M", "A", "??", "R", "C"):
                files.add(path)
        for rel in files:
            s = src / rel
            d = dst / rel
            if not s.is_file():
                continue
            d.parent.mkdir(parents=True, exist_ok=True)
            try:
                shutil.copy2(s, d)
            except OSError:
                continue

    @staticmethod
    def _persist_diff_journal(agent_id: str, diff_text: str) -> str:
        try:
            from argos import config
            d = config.config_dir() / "workflow" / "diffs"
            d.mkdir(parents=True, exist_ok=True)
            p = d / f"{agent_id}.diff"
            safe = p
            p.write_text(diff_text, encoding="utf-8")
            return str(safe)
        except Exception:  # noqa: BLE001
            return ""

    @classmethod
    def for_test(cls, *, workspace: Path, model_factory: Callable[[str | None], Any]) -> "SubAgentFactory":
        from argos.core.models import CredentialPool
        from argos.core.verify_gate import Verifier
        from argos.memory.store import ArgosStore
        from argos.sandbox.egress import EgressPolicy
        from argos.tools.receipts import ReceiptSigner

        return cls(
            base_workspace=workspace,
            pool=CredentialPool(["test"]),
            egress=EgressPolicy(llm_hosts=set(), search_hosts=set(), mcp_hosts=set()),
            signer=ReceiptSigner(key=os.urandom(32)),
            verifier=Verifier(max_rounds=2),
            store_factory=lambda: ArgosStore(db_path=":memory:"),
            model_factory=model_factory,
        )
