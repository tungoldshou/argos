"""candidates:distill 产物的落盘存储层(晋升前的候选区)。

设计:
- 候选区 != skills_root —— skills 加载器不读这里,未晋升绝不生效。
- 目录:<root>/<name>-<run12>/{SKILL.md, meta.json};root 参数注入(默认 ~/.argos/learning/candidates)。
- 消费标记写 meta.json(consumed/consumed_reason),不删目录 —— 审计可见。
- E4 纵深防御:self_verified 显式落盘进 meta;list_unconsumed 拒绝 self_verified=True 的候选。
- 一切 IO 失败诚实降级:log + 返回空/None,绝不抛(学习路径不挂主任务)。
"""
from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

# 复用 memory/auto.py 既有脱敏函数(9 条正则覆盖 sk-ant- / ghp_ / AKIA /
# PRIVATE KEY / password= 等);meta.json 里的 goal / verify_cmd / workspace
# 不经 distiller,需在此处独立脱敏。
from argos_agent.memory.auto import _redact_secrets

log = logging.getLogger(__name__)

DEFAULT_ROOT = Path.home() / ".argos" / "learning" / "candidates"


@dataclass(frozen=True, slots=True)
class StoredCandidate:
    """候选区里的一条已落盘候选。"""
    name: str
    body_markdown: str
    verify_cmd: str | None
    source_run: str
    workspace: str | None
    goal: str
    path: Path
    self_verified: bool = False   # E4 来源记录:True 的候选永远不会出现(双保险见 list_unconsumed)


def _dir_for(root: Path, name: str, source_run: str) -> Path:
    safe_name = Path(name).name or "learned"  # 剥目录分隔符,防穿越
    return root / f"{safe_name}-{source_run[:12]}"


def save_candidate(cand: Any, *, root: Path, source_run: str,
                   workspace: str | None, goal: str,
                   self_verified: bool = False) -> Path | None:
    """落盘一个 SkillCandidate。同 (name, run) 幂等覆盖。失败返 None。

    self_verified 显式落盘进 meta(E4 来源记录)——正常路径恒 False
    (hook 的 _on_passed 只在用户级验证通过时可达),记录它是为了纵深防御。
    """
    try:
        d = _dir_for(root, getattr(cand, "name", "learned"), source_run)
        d.mkdir(parents=True, exist_ok=True)
        # 脱敏:goal / verify_cmd / workspace 不经 distiller,在落盘前独立脱敏
        safe_goal = _redact_secrets(goal or "")
        raw_verify = getattr(cand, "verify_cmd", None)
        safe_verify = _redact_secrets(raw_verify) if raw_verify else None
        safe_workspace = _redact_secrets(workspace) if workspace else workspace
        # 原子写(同 promotion_gate._atomic_write_skill 约定)
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
            }, ensure_ascii=False, indent=2)),
        ):
            tmp = d / (fname + ".tmp")
            tmp.write_text(content, encoding="utf-8")
            tmp.replace(d / fname)
        return d
    except Exception as e:  # noqa: BLE001 — 学习路径不挂主任务
        log.warning("candidates: save 失败(%s): %s", source_run, e)
        return None


def list_unconsumed(root: Path) -> list[StoredCandidate]:
    """扫描候选区,返回未消费候选。坏目录跳过;self_verified 拒绝(E4 双保险)。

    返回顺序为目录名字典序,非时间序。
    """
    out: list[StoredCandidate] = []
    if not root.exists():
        return out
    for meta_path in sorted(root.glob("*/meta.json")):
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            if meta.get("consumed"):
                continue
            if meta.get("self_verified"):
                # E4 纵深防御:自验证来源永远不进 Dream 材料(上游本不该落盘,双保险)
                log.warning("candidates: 拒绝 self_verified 候选 %s", meta_path.parent)
                continue
            body = (meta_path.parent / "SKILL.md").read_text(encoding="utf-8")
            out.append(StoredCandidate(
                name=str(meta.get("name", "")),
                body_markdown=body,
                verify_cmd=meta.get("verify_cmd"),
                source_run=str(meta.get("source_run", "")),
                workspace=meta.get("workspace"),
                goal=str(meta.get("goal", "")),
                path=meta_path.parent,
                self_verified=bool(meta.get("self_verified", False)),
            ))
        except Exception as e:  # noqa: BLE001
            log.warning("candidates: 跳过坏候选 %s: %s", meta_path.parent, e)
    return out


def mark_consumed(cand_dir: Path, *, reason: str) -> bool:
    """标记候选已消费(promoted / rejected / workspace_gone)。失败返 False。"""
    meta_path = cand_dir / "meta.json"
    try:
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        meta["consumed"] = True
        meta["consumed_reason"] = reason
        meta["consumed_at"] = time.time()
        tmp = meta_path.parent / (meta_path.name + ".tmp")
        tmp.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(meta_path)
        return True
    except Exception as e:  # noqa: BLE001
        log.warning("candidates: mark_consumed 失败 %s: %s", cand_dir, e)
        return False
