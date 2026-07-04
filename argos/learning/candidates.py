from __future__ import annotations

import json
import logging
import os
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from argos import config
from argos.memory.auto import _redact_secrets

log = logging.getLogger(__name__)

DEFAULT_ROOT: Path | None = None


def default_root(path: Path | None = None) -> Path:
    return Path(path or DEFAULT_ROOT or (config.config_dir() / "learning" / "candidates"))


def _unique_tmp(target: Path) -> Path:
    return target.with_name(f"{target.name}.{os.getpid()}.{uuid.uuid4().hex}.tmp")


@dataclass(frozen=True, slots=True)
class StoredCandidate:
    name: str
    body_markdown: str
    verify_cmd: str | None
    source_run: str
    workspace: str | None
    goal: str
    path: Path
    self_verified: bool = False
    # Performance metrics from distiller (default-safe for old candidates lacking these fields)
    verdict_status: str | None = None
    tokens_in: int = 0
    tokens_out: int = 0
    cost_usd: float | None = None
    steps: int = 0


def _dir_for(root: Path, name: str, source_run: str) -> Path:
    safe_name = Path(name).name or "learned"
    return root / f"{safe_name}-{source_run[:12]}"


def save_candidate(cand: Any, *, root: Path, source_run: str,
                   workspace: str | None, goal: str,
                   self_verified: bool = False) -> Path | None:
    try:
        d = _dir_for(root, getattr(cand, "name", "learned"), source_run)
        d.mkdir(parents=True, exist_ok=True)
        safe_goal = _redact_secrets(goal or "")
        raw_verify = getattr(cand, "verify_cmd", None)
        safe_verify = _redact_secrets(raw_verify) if raw_verify else None
        safe_workspace = _redact_secrets(workspace) if workspace else workspace
        for fname, content in (
            ("SKILL.md", getattr(cand, "body_markdown", "")),
            ("meta.json", json.dumps({
                "name": getattr(cand, "name", "learned"),
                "source_run": source_run,
                "verify_cmd": safe_verify,
                "workspace": safe_workspace,
                "goal": safe_goal,
                "created_at": time.time(),
                "consumed": False,
                "consumed_reason": None,
                "self_verified": bool(self_verified),
                # Performance metrics from distiller (omitted when absent = old candidates stay compatible)
                "verdict_status": getattr(cand, "verdict_status", None),
                "tokens_in": getattr(cand, "tokens_in", 0),
                "tokens_out": getattr(cand, "tokens_out", 0),
                "cost_usd": getattr(cand, "cost_usd", None),
                "steps": getattr(cand, "steps", 0),
            }, ensure_ascii=False, indent=2)),
        ):
            target = d / fname
            tmp = _unique_tmp(target)
            tmp.write_text(content, encoding="utf-8")
            tmp.replace(target)
        return d
    except Exception as e:  # noqa: BLE001
        log.warning("candidates: save 失败(%s): %s", source_run, e)
        return None


def list_unconsumed(root: Path) -> list[StoredCandidate]:
    out: list[StoredCandidate] = []
    if not root.exists():
        return out
    for meta_path in sorted(root.glob("*/meta.json")):
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            if meta.get("consumed"):
                continue
            if meta.get("self_verified"):
                log.warning("candidates: 拒绝 self_verified 候选 %s", meta_path.parent)
                continue
            body = (meta_path.parent / "SKILL.md").read_text(encoding="utf-8")
            raw_cost = meta.get("cost_usd")
            out.append(StoredCandidate(
                name=str(meta.get("name", "")),
                body_markdown=body,
                verify_cmd=meta.get("verify_cmd"),
                source_run=str(meta.get("source_run", "")),
                workspace=meta.get("workspace"),
                goal=str(meta.get("goal", "")),
                path=meta_path.parent,
                self_verified=bool(meta.get("self_verified", False)),
                verdict_status=meta.get("verdict_status"),
                tokens_in=int(meta.get("tokens_in") or 0),
                tokens_out=int(meta.get("tokens_out") or 0),
                cost_usd=float(raw_cost) if raw_cost is not None else None,
                steps=int(meta.get("steps") or 0),
            ))
        except Exception as e:  # noqa: BLE001
            log.warning("candidates: 跳过坏候选 %s: %s", meta_path.parent, e)
    return out


def mark_consumed(cand_dir: Path, *, reason: str) -> bool:
    meta_path = cand_dir / "meta.json"
    try:
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        meta["consumed"] = True
        meta["consumed_reason"] = reason
        meta["consumed_at"] = time.time()
        tmp = _unique_tmp(meta_path)
        tmp.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(meta_path)
        return True
    except Exception as e:  # noqa: BLE001
        log.warning("candidates: mark_consumed 失败 %s: %s", cand_dir, e)
        return False
