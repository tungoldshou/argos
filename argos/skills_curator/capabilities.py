"""#10 T2 frontmatter 解析 + capability 校验 + builtin 保护。

SKILL.md frontmatter 必填字段(spec §6.1):
  name:        str (^[a-z][a-z0-9-]{2,32}$)
  version:     str (semver)
  capabilities: list[str] ⊆ {read, write, execute, network}
  enabled:     bool   ← 装时强制 false(防"装了就能跑")
  description: str
  author:      str

D11:4 个 capability 粗粒度(read/write/execute/network)
D7:builtin 3 名硬拒 install/remove
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from argos.skills_curator import index as _index_mod
from argos.skills_curator.index import BUILTIN_NAMES

_FRONTMATTER = re.compile(r"^---\n(.*?)\n---\n(.*)$", re.DOTALL)


@dataclass(frozen=True, slots=True)
class InstalledSkill:
    name: str
    version: str
    author: str
    capabilities: tuple[str, ...]
    enabled: bool
    description: str
    path: Path
    source: str = ""  # index 远端 URL;builtin 留空

    def to_card_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "version": self.version,
            "author": self.author,
            "capabilities": list(self.capabilities),
            "enabled": self.enabled,
            "description": self.description,
            "path": str(self.path),
            "source": self.source,
        }


def parse_frontmatter(text: str) -> dict:
    """从 SKILL.md 文本抽 YAML frontmatter dict;解析失败 → raise ValueError."""
    m = _FRONTMATTER.match(text)
    if not m:
        raise ValueError("missing --- YAML --- frontmatter")
    try:
        meta = yaml.safe_load(m.group(1)) or {}
    except Exception as e:  # noqa: BLE001
        raise ValueError(f"frontmatter YAML parse failed: {e}") from e
    if not isinstance(meta, dict):
        raise ValueError("frontmatter is not a dict")
    return meta


def validate_skill_meta(meta: dict, *, name: str) -> list[str]:
    """返回错误 list(空 = ok)。缺 capabilities / 未知值 / 缺 name 都报。"""
    errors: list[str] = []
    if not meta.get("name"):
        errors.append("frontmatter: missing 'name'")
    elif meta["name"] != name:
        errors.append(f"frontmatter: name {meta['name']!r} != filename {name!r}")
    caps = meta.get("capabilities")
    if not caps:
        errors.append(
            "frontmatter: missing 'capabilities' (must be list of {read,write,execute,network})"
        )
    elif not isinstance(caps, list):
        errors.append("frontmatter: 'capabilities' must be list")
    else:
        from argos.skills_curator.index import VALID_CAPABILITIES
        for c in caps:
            if c not in VALID_CAPABILITIES:
                errors.append(
                    f"frontmatter: unknown capability {c!r} "
                    f"(valid: {sorted(VALID_CAPABILITIES)})"
                )
    if not meta.get("version"):
        errors.append("frontmatter: missing 'version'")
    return errors


def read_installed_skill(path: Path) -> InstalledSkill | None:
    """读单个 SKILL.md 返 InstalledSkill;解析失败 → None(不抛)."""
    try:
        text = path.read_text("utf-8")
        meta = parse_frontmatter(text)
    except (OSError, ValueError):
        return None
    name = path.parent.name
    return InstalledSkill(
        name=name,
        version=str(meta.get("version", "0.0.0")),
        author=str(meta.get("author", "anonymous")),
        capabilities=tuple(meta.get("capabilities", ["read"])),
        enabled=bool(meta.get("enabled", False)),
        description=str(meta.get("description", ""))[:280],
        path=path,
        source=str(meta.get("source", "")),
    )


def list_installed(*, base_dir: Path | None = None) -> list[InstalledSkill]:
    """扫 `~/.argos/skills/*/SKILL.md` 返 list(按 name 升序)。"""
    root = base_dir or _index_mod._skills_root()
    if not root.exists():
        return []
    out: list[InstalledSkill] = []
    for d in sorted(p for p in root.iterdir() if p.is_dir() and not p.name.startswith(".")):
        skill_md = d / "SKILL.md"
        if not skill_md.exists():
            continue
        s = read_installed_skill(skill_md)
        if s is not None:
            out.append(s)
    return out


__all__ = [
    "BUILTIN_NAMES",
    "InstalledSkill",
    "list_installed",
    "parse_frontmatter",
    "read_installed_skill",
    "validate_skill_meta",
]
