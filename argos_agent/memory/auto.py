"""#9 Auto memory 4 tier 模块(扩展 argos_agent.memory,不污染任务历史接口)。

四层记忆:user(全局用户偏好) / project(per-repo 约定) / skill(per-skill 失败) /
session(per-run 临时,30 天 rotate)。Append-only JSONL + threading.Lock,无 sqlite
新依赖。详见 docs/superpowers/specs/2026-06-06-auto-memory-design.md。

D1:JSONL(与 RunStore 同模式)
D3:CLAUDE.md 注入在 untrusted 围栏内的 <memory_context> 段
D5:project_id = sha1(repo_root | cwd)[:16]
D20:threading.Lock 包裹写
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import threading
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Iterable, Literal

# ── 公共类型(spec §4.2)───────────────────────────────────────────────────────
Scope = Literal["user", "project", "skill", "session"]
Type = Literal["preference", "convention", "failure", "decision", "fact"]


@dataclass(frozen=True, slots=True)
class MemoryEntry:
    id: str
    type: Type
    scope: Scope
    key: str
    value: str
    confidence: float
    evidence: tuple[str, ...]
    ts: float
    last_used_at: float
    use_count: int
    skill_name: str | None = None
    project_id: str | None = None
    session_id: str | None = None


# ── 路径解析 ─────────────────────────────────────────────────────────────────
def _root() -> Path:
    """记忆根目录:env var 优先(测试用),否则 ~/.argos/memory/。"""
    override = os.environ.get("ARGOS_MEMORY_DIR")
    return Path(override) if override else Path.home() / ".argos" / "memory"


def _user_path() -> Path:
    return _root() / "user.jsonl"


def _project_path(project_id: str) -> Path:
    return _root() / "projects" / f"{project_id}.jsonl"


def _skill_path(skill_name: str) -> Path:
    return _root() / "skills" / f"{skill_name}.jsonl"


def _session_path(session_id: str) -> Path:
    return _root() / "sessions" / f"{session_id}.jsonl"


def project_id_for(cwd: Path | None = None) -> str:
    """计算 project_id:用 cwd 绝对路径 sha1 前 16。无 .git 也行(本期不 walk up git)。"""
    p = (cwd or Path.cwd()).resolve()
    return hashlib.sha1(str(p).encode("utf-8")).hexdigest()[:16]


# ── 读写 ─────────────────────────────────────────────────────────────────────
_write_lock = threading.Lock()
_PROJECT_ID_CACHE: dict[str, str] = {}


def _read_jsonl(path: Path) -> list[MemoryEntry]:
    """读 JSONL,坏行跳过,文件不存在返空(诚实空态)。"""
    if not path.exists():
        return []
    out: list[MemoryEntry] = []
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return []  # IOError 静默返空(spec §10)
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            d = json.loads(line)
        except json.JSONDecodeError:
            continue  # 一行坏数据不毁整个记忆
        try:
            out.append(MemoryEntry(
                id=d["id"],
                type=d["type"],
                scope=d["scope"],
                key=d["key"],
                value=d["value"],
                confidence=float(d["confidence"]),
                evidence=tuple(d.get("evidence") or ()),
                ts=float(d["ts"]),
                last_used_at=float(d.get("last_used_at") or d["ts"]),
                use_count=int(d.get("use_count") or 0),
                skill_name=d.get("skill_name"),
                project_id=d.get("project_id"),
                session_id=d.get("session_id"),
            ))
        except (KeyError, ValueError, TypeError):
            continue  # schema 不全的行也跳过
    return out


def _append_jsonl(path: Path, entry: MemoryEntry) -> None:
    """追加一条记忆(JSONL),parent dirs 自动建。失败静默(spec §10)。"""
    with _write_lock:
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            d = asdict(entry)
            d["evidence"] = list(entry.evidence)  # tuple → list(JSON 友好)
            with path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(d, ensure_ascii=False) + "\n")
        except OSError:
            pass  # 磁盘满/权限 — 静默,记忆是 nice-to-have
