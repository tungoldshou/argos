"""Skills 仓库 —— 内置库 + 用户/社区导入,run 开始按 goal 召回。

文件布局:每个 skill 一个 markdown,YAML frontmatter(name/description/trust/enabled/source?) + 正文。
trust: builtin | imported | user_created
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

import yaml

BUILTIN_DIR = Path(__file__).parent / "skills_builtin"
USER_DIR = Path.home() / ".argos" / "skills"
MAX_SKILL_CHARS = 3000  # 导入上限


Trust = Literal["builtin", "imported", "user_created"]


@dataclass
class Skill:
    name: str
    description: str
    trust: Trust
    enabled: bool
    body: str
    source: str = ""        # 导入来源 URL / "inline" / 其它
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
    for d in (BUILTIN_DIR, USER_DIR):
        if not d.exists():
            continue
        for p in sorted(d.glob("*.md")):
            s = _parse(p)
            if s and s.name not in out:  # builtin 优先,后到的 user 不覆盖
                out[s.name] = s
    return list(out.values())


def toggle(name: str, *, enabled: bool) -> bool:
    """切换 enabled 写回原文件。"""
    for d in (BUILTIN_DIR, USER_DIR):
        p = d / f"{name}.md"
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
    """从字符串导入一个 skill(URL fetch 是 Task 6 后端的事,这里只接内容)。
    写入 USER_DIR。同名 builtin 不覆盖(用户要覆盖 builtin 请手动删 builtin 目录)。
    """
    if len(content) > MAX_SKILL_CHARS:
        raise ValueError(f"skill body too long (> {MAX_SKILL_CHARS} chars)")
    s = _parse_string(content)
    if s is None:
        raise ValueError("invalid skill markdown (need --- YAML --- frontmatter with name)")
    s.source = source
    USER_DIR.mkdir(parents=True, exist_ok=True)
    (USER_DIR / f"{s.name}.md").write_text(_serialize(s), encoding="utf-8")
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


# ── recall:用 embedding 算余弦,top-k + sim_min 过滤 ─────────────────────────

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


def recall(goal: str, *, k: int = 3, sim_min: float = 0.4) -> list[Skill]:
    """按 goal 语义相似度取 top-k 启用的 skill(复用记忆同款 embedder,模型不绑定)。
    embedder 来自 config.active_embedder():未配 embedding / 非 OpenAI 协议 / 无 key → None →
    返回空(降级,不绑定 MiniMax、不偷调模型);embedding 调用失败也降级返空。"""
    if not goal.strip():
        return []
    skills_all = [s for s in load_all() if s.enabled]
    if not skills_all:
        return []
    from argos_agent import config
    embedder = config.active_embedder()
    if embedder is None:
        return []  # 未配 embedding(或 Anthropic 端无 embeddings)→ 无语义召回,诚实降级
    try:
        goal_emb = embedder.embed([goal])[0]
        embeds = embedder.embed([f"{s.name}\n{s.description}" for s in skills_all])
    except Exception:
        return []  # embedding 调用失败 = 无 recall(降级,不抛)
    scored = sorted(
        ((_cosine(goal_emb, e), s) for s, e in zip(skills_all, embeds)),
        key=lambda x: x[0], reverse=True,
    )
    return [s for sim, s in scored[:k] if sim >= sim_min]
