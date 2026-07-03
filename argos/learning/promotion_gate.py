from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from argos.skills_curator.index import BUILTIN_NAMES


@dataclass(frozen=True, slots=True)
class PromotionResult:

    promoted: bool
    reason: str
    a_passed: int = 0
    b_passed: int = 0
    a_total: int = 0
    b_total: int = 0


def _is_pass(pass_status: str | None) -> bool:
    try:
        from argos.eval.runner import PASS_PASSED
        return pass_status == PASS_PASSED
    except Exception:  # noqa: BLE001
        return pass_status == "passed"


def _skill_md_path_for(skills_root: Path, name: str) -> Path:
    return skills_root / name / "SKILL.md"


def _atomic_write_skill(skill_md: Path, content: str) -> None:
    import os
    import uuid

    skill_md.parent.mkdir(parents=True, exist_ok=True)
    tmp = skill_md.with_name(
        f"{skill_md.name}.{os.getpid()}.{uuid.uuid4().hex}.tmp")
    tmp.write_text(content, encoding="utf-8")
    tmp.replace(skill_md)


def _rebuild_index(skills_root: Path) -> None:
    try:
        from argos.skills_curator import index as _idx
        # ponytail: load_cache is best-effort — failure doesn't block promotion
        _idx.load_cache(base_dir=skills_root)
    except Exception:  # noqa: BLE001
        pass


def _enable_in_body(body: str) -> str:
    """Rewrite 'enabled: false' → 'enabled: true' in the YAML frontmatter only.

    Scans only the first frontmatter block (lines between the first two '---'
    fences) to avoid matching body text.  If no such line is found the body is
    returned unchanged (safe no-op).
    """
    lines = body.splitlines(keepends=True)
    if not lines or lines[0].strip() != "---":
        return body
    in_fm = False
    fence_seen = 0
    out: list[str] = []
    for line in lines:
        stripped = line.strip()
        if stripped == "---":
            fence_seen += 1
            in_fm = fence_seen == 1
            out.append(line)
            continue
        if in_fm and stripped.lower().replace(" ", "") == "enabled:false":
            # ponytail: normalise spacing/case so distiller format drift can't
            # silently leave a gate-winning skill disabled.
            out.append(line.replace("enabled: false", "enabled: true", 1)
                          .replace("enabled:false", "enabled: true", 1)
                          .replace("enabled: False", "enabled: true", 1))
        else:
            out.append(line)
    return "".join(out)


def promote(
    *,
    candidate: Any,      # SkillCandidate
    tasks: list,         # list[EvalTask]
    runner: Any,
    runner_b: Any = None,
    skills_root: Path,
) -> PromotionResult:
    import logging as _log
    log = _log.getLogger(__name__)

    name = getattr(candidate, "name", "")
    body = getattr(candidate, "body_markdown", "")
    if not name or not body:
        return PromotionResult(promoted=False, reason="candidate_empty")

    if name in BUILTIN_NAMES:
        return PromotionResult(
            promoted=False, reason=f"builtin_protected:{name}",
        )

    skill_md = _skill_md_path_for(skills_root, name)
    if skill_md.exists():
        try:
            existing = skill_md.read_text(encoding="utf-8")
            lines = existing.splitlines()
            if not lines or lines[0].strip() != "---":
                is_learned = False
            else:
                fm_lines: list[str] = []
                inside = False
                fence_count = 0
                for line in lines:
                    if line.strip() == "---":
                        fence_count += 1
                        if fence_count == 1:
                            inside = True
                            continue
                        else:
                            inside = False
                            break
                    if inside:
                        fm_lines.append(line)
                fm = "\n".join(fm_lines)
                is_learned = "source_run:" in fm or "source_runs:" in fm
        except Exception:  # noqa: BLE001
            return PromotionResult(
                promoted=False, reason="name_collision_unreadable",
            )
        if not is_learned:
            return PromotionResult(
                promoted=False, reason=f"name_collision:{name}",
            )
        log.info("promote: overwriting existing learned skill %r", name)

    a_passed = 0
    b_passed = 0
    a_total = 0
    b_total = 0
    try:
        for task in tasks:
            rb = runner_b if runner_b is not None else runner
            try:
                a = runner.run(task, model_tier="default")
            except Exception as e:  # noqa: BLE001
                a = None
            try:
                b = rb.run(task, model_tier="default")
            except Exception as e:  # noqa: BLE001
                b = None
            a_total += 1
            b_total += 1
            if a is not None and _is_pass(getattr(a, "pass_status", None)):
                a_passed += 1
            if b is not None and _is_pass(getattr(b, "pass_status", None)):
                b_passed += 1
    except Exception as e:  # noqa: BLE001
        return PromotionResult(
            promoted=False, reason=f"runner_error:{type(e).__name__}",
        )

    if b_passed <= a_passed:
        return PromotionResult(
            promoted=False,
            reason=f"no_improvement(a={a_passed}/{a_total},b={b_passed}/{b_total})",
            a_passed=a_passed, b_passed=b_passed,
            a_total=a_total, b_total=b_total,
        )

    enabled_body = _enable_in_body(body)
    try:
        _atomic_write_skill(skill_md, enabled_body)
    except Exception as e:  # noqa: BLE001
        return PromotionResult(
            promoted=False, reason=f"write_failed:{type(e).__name__}:{e}",
            a_passed=a_passed, b_passed=b_passed,
            a_total=a_total, b_total=b_total,
        )

    _rebuild_index(skills_root)

    log.info(
        "auto-enabled skill %r after A/B gate (a=%d/%d → b=%d/%d); "
        "active on next run",
        name, a_passed, a_total, b_passed, b_total,
    )
    return PromotionResult(
        promoted=True, reason="improved",
        a_passed=a_passed, b_passed=b_passed,
        a_total=a_total, b_total=b_total,
    )
