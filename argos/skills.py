"""Internal documentation."""
from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

import yaml

from argos import config

BUILTIN_DIR = Path(__file__).parent / "skills_builtin"
USER_DIR: Path | None = None
MAX_SKILL_CHARS = 3000


def user_dir(path: Path | None = None) -> Path:
    return Path(
        path or USER_DIR or (
            Path(config.get("ARGOS_CONFIG_DIR") or (Path.home() / ".argos")).expanduser()
            / "skills"
        )
    )


Trust = Literal["builtin", "imported", "user_created"]


@dataclass
class Skill:
    name: str
    description: str
    trust: Trust
    enabled: bool
    body: str
    source: str = ""
    path: Path = field(default_factory=Path)

    def to_dict(self) -> dict:
        return {
            "name": self.name, "description": self.description,
            "trust": self.trust, "enabled": self.enabled, "source": self.source,
        }


_FRONTMATTER = re.compile(r"^---\n(.*?)\n---\n(.*)$", re.DOTALL)


def _parse(p: Path) -> Skill | None:
    try:
        text = p.read_text(encoding="utf-8")
    except Exception:
        return None
    m = _FRONTMATTER.match(text)
    if not m:
        return None
    try:
        meta = yaml.safe_load(m.group(1)) or {}
    except Exception:
        return None
    if not isinstance(meta, dict) or "name" not in meta:
        return None
    return Skill(
        name=str(meta["name"]),
        description=str(meta.get("description", "")),
        trust=meta.get("trust", "user_created"),
        enabled=bool(meta.get("enabled", True)),
        body=m.group(2),
        source=str(meta.get("source", "")),
        path=p,
    )


def _serialize(skill: Skill) -> str:
    meta = {
        "name": skill.name, "description": skill.description,
        "trust": skill.trust, "enabled": skill.enabled,
    }
    if skill.source:
        meta["source"] = skill.source
    return f"---\n{yaml.safe_dump(meta, allow_unicode=True, sort_keys=False)}---\n{skill.body}"


def load_all() -> list[Skill]:
    out: dict[str, Skill] = {}
    for d in (BUILTIN_DIR, user_dir()):
        if not d.exists():
            continue
        for p in sorted(d.glob("*.md")):
            s = _parse(p)
            if s and s.name not in out:
                out[s.name] = s
        for p in sorted(d.glob("*/SKILL.md")):
            s = _parse(p)
            if s and s.name not in out:
                out[s.name] = s
    return list(out.values())


def toggle(name: str, *, enabled: bool) -> bool:
    """Internal documentation."""
    for d in (BUILTIN_DIR, user_dir()):
        p = d / f"{name}.md"
        if not p.exists():
            p = d / name / "SKILL.md"
        if not p.exists():
            continue
        s = _parse(p)
        if s is None:
            return False
        s.enabled = enabled
        p.write_text(_serialize(s), encoding="utf-8")
        return True
    return False


def import_skill(*, content: str, source: str = "") -> Skill:
    """Internal documentation."""
    if len(content) > MAX_SKILL_CHARS:
        raise ValueError(f"skill body too long (> {MAX_SKILL_CHARS} chars)")
    s = _parse_string(content)
    if s is None:
        raise ValueError("invalid skill markdown (need --- YAML --- frontmatter with name)")
    s.source = source
    root = user_dir()
    root.mkdir(parents=True, exist_ok=True)
    (root / f"{s.name}.md").write_text(_serialize(s), encoding="utf-8")
    return s


def _parse_string(content: str) -> Skill | None:
    m = _FRONTMATTER.match(content)
    if not m:
        return None
    try:
        meta = yaml.safe_load(m.group(1)) or {}
    except Exception:
        return None
    if not isinstance(meta, dict) or "name" not in meta:
        return None
    return Skill(
        name=str(meta["name"]), description=str(meta.get("description", "")),
        trust=meta.get("trust", "user_created"), enabled=bool(meta.get("enabled", True)),
        body=m.group(2), source="",
    )



def _cosine(a: list[float], b: list[float]) -> float:
    s = 0.0
    na = 0.0
    nb = 0.0
    for x, y in zip(a, b):
        s += x * y
        na += x * x
        nb += y * y
    if na == 0 or nb == 0:
        return 0.0
    return s / math.sqrt(na * nb)


def _tokens(text: str) -> set[str]:
    """Internal documentation."""
    low = text.lower()
    return set(re.findall(r"[a-z0-9]+", low)) | set(re.findall(r"[一-鿿]", low))


def _keyword_score(goal: str, s: "Skill") -> float:
    """Internal documentation."""
    g = _tokens(goal)
    if not g:
        return 0.0
    st = _tokens(f"{s.name} {s.description}")
    return len(g & st) / len(g)


def recall(goal: str, *, k: int = 3, sim_min: float = 0.4) -> list[Skill]:
    """Internal documentation."""
    if not goal.strip():
        return []
    skills_all = [s for s in load_all() if s.enabled]
    if not skills_all:
        return []
    from argos import config
    embedder = config.active_embedder()
    if embedder is not None:
        try:
            goal_emb = embedder.embed([goal])[0]
            embeds = embedder.embed([f"{s.name}\n{s.description}" for s in skills_all])
            scored = sorted(
                ((_cosine(goal_emb, e), s) for s, e in zip(skills_all, embeds)),
                key=lambda x: x[0], reverse=True,
            )
            return [s for sim, s in scored[:k] if sim >= sim_min]
        except Exception:
            pass
    kw = sorted(((_keyword_score(goal, s), s) for s in skills_all),
                key=lambda x: x[0], reverse=True)
    return [s for sc, s in kw[:k] if sc > 0.0]
