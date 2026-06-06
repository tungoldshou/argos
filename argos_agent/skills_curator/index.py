"""#10 T1 Index schema + 本地 cache + refresh。

远端 raw GitHub `index.json`(只读,作者 PR 维护):
  {version, generated_at, skills: [{name, version, author, sha256, description,
   skill_md_url, compatibility, capabilities, size_bytes}, ...]}

本地 `~/.argos/skills/index.json` 是远端副本(atomic write)。
sha256 校验:对账 index.json 自身的哈希(远端维护者写的 sha 在 index.json.sha256 旁)

D1:GitHub raw 托管
D4:schema 宽松兼容(未知字段忽略)
D7:builtin 3 名(verify/security-review/simplify)受保护
D9:不重写 skills.py / skills_runtime
"""
from __future__ import annotations

import json
import re
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

DEFAULT_INDEX_URL = (
    "https://raw.githubusercontent.com/tungoldshou/argos-skills-index/main/index.json"
)

Capability = Literal["read", "write", "execute", "network"]
VALID_CAPABILITIES: frozenset[str] = frozenset({"read", "write", "execute", "network"})

BUILTIN_NAMES: frozenset[str] = frozenset({"verify", "security-review", "simplify"})

# 名称格式(spec §4.3)
_NAME_RE = re.compile(r"^[a-z][a-z0-9-]{2,32}$")
_SEMVER_RE = re.compile(r"^\d+\.\d+\.\d+(-[a-z0-9.]+)?$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


@dataclass(frozen=True, slots=True)
class IndexEntry:
    name: str
    version: str
    author: str
    sha256: str
    description: str
    skill_md_url: str
    compatibility: str
    capabilities: tuple[str, ...]
    size_bytes: int

    def is_builtin(self) -> bool:
        return self.name in BUILTIN_NAMES


@dataclass(frozen=True, slots=True)
class IndexCache:
    version: int
    generated_at: float
    skills: tuple[IndexEntry, ...]

    def find(self, name: str) -> IndexEntry | None:
        for e in self.skills:
            if e.name == name:
                return e
        return None


class IndexFetchError(RuntimeError):
    """远端 index 拉取失败(网络 / 404 / JSON 解析)。"""


def _skills_root() -> Path:
    return Path.home() / ".argos" / "skills"


def _parse_entry(raw: dict) -> IndexEntry:
    name = str(raw["name"])
    if not _NAME_RE.match(name):
        raise ValueError(f"invalid name {name!r}")
    version = str(raw["version"])
    if not _SEMVER_RE.match(version):
        raise ValueError(f"invalid version {version!r} for {name!r}")
    sha = str(raw["sha256"]).lower()
    if not _SHA256_RE.match(sha):
        raise ValueError(f"invalid sha256 {sha[:12]}... for {name!r}")
    caps = tuple(str(c) for c in raw.get("capabilities", []))
    for c in caps:
        if c not in VALID_CAPABILITIES:
            raise ValueError(f"invalid capability {c!r} for {name!r}")
    return IndexEntry(
        name=name,
        version=version,
        author=str(raw.get("author", "anonymous")),
        sha256=sha,
        description=str(raw.get("description", ""))[:280],
        skill_md_url=str(raw["skill_md_url"]),
        compatibility=str(raw.get("compatibility", ">=0.0.0")),
        capabilities=caps,
        size_bytes=int(raw.get("size_bytes", 0)),
    )


def fetch_remote(*, url: str = DEFAULT_INDEX_URL, timeout: float = 10.0) -> IndexCache:
    """HTTP GET index.json,parse,validate known fields(未知字段忽略)。"""
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:
            data = json.loads(r.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError) as e:
        raise IndexFetchError(f"failed to fetch {url}: {type(e).__name__}: {e}") from e
    except json.JSONDecodeError as e:
        raise IndexFetchError(f"index.json: invalid JSON: {e}") from e

    if not isinstance(data, dict):
        raise IndexFetchError(f"index.json: top-level not a dict: {type(data).__name__}")

    raw_skills = data.get("skills", [])
    if not isinstance(raw_skills, list):
        raise IndexFetchError("index.json: 'skills' not a list")

    entries: list[IndexEntry] = []
    for raw in raw_skills:
        if not isinstance(raw, dict):
            continue
        try:
            entries.append(_parse_entry(raw))
        except (ValueError, KeyError):
            continue  # D4 宽松:坏行跳过,不 crash 整 cache

    return IndexCache(
        version=int(data.get("version", 1)),
        generated_at=float(data.get("generated_at", time.time())),
        skills=tuple(entries),
    )


def save_cache(cache: IndexCache, *, base_dir: Path | None = None) -> Path:
    """原子写 `index.json` 到 base_dir;base 缺省 = ~/.argos/skills/."""
    root = base_dir or _skills_root()
    root.mkdir(parents=True, exist_ok=True)
    target = root / "index.json"
    tmp = root / "index.json.tmp"
    payload = {
        "version": cache.version,
        "generated_at": cache.generated_at,
        "skills": [
            {
                "name": e.name,
                "version": e.version,
                "author": e.author,
                "sha256": e.sha256,
                "description": e.description,
                "skill_md_url": e.skill_md_url,
                "compatibility": e.compatibility,
                "capabilities": list(e.capabilities),
                "size_bytes": e.size_bytes,
            }
            for e in cache.skills
        ],
    }
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(target)  # atomic on POSIX
    return target


def load_cache(*, base_dir: Path | None = None) -> IndexCache | None:
    p = (base_dir or _skills_root()) / "index.json"
    if not p.exists():
        return None
    try:
        data = json.loads(p.read_text("utf-8"))
    except (json.JSONDecodeError, OSError):
        return None
    entries: list[IndexEntry] = []
    for raw in data.get("skills", []):
        if not isinstance(raw, dict):
            continue
        try:
            entries.append(_parse_entry(raw))
        except (ValueError, KeyError):
            continue
    return IndexCache(
        version=int(data.get("version", 1)),
        generated_at=float(data.get("generated_at", 0.0)),
        skills=tuple(entries),
    )


def cache_age_days(*, base_dir: Path | None = None) -> float | None:
    p = (base_dir or _skills_root()) / "index.json"
    if not p.exists():
        return None
    return (time.time() - p.stat().st_mtime) / 86400.0
