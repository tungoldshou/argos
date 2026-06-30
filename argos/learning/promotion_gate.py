"""promotion_gate:A/B 评估 → 仅当候选技能实测提升通过率才晋升。

设计要点(任务护城河):
- 同 model_tier 跑两次(A=无技能 hint, B=有技能 hint);loop_factory 是 caller 注入的,
  本函数只负责"用同一语料各跑一次 + 比较"。
- 判定:B 通过任务数严格 > A 通过任务数(平手 / 退化 → 不晋升)。
- builtin 名字硬拒(reuse skills_curator.index.BUILTIN_NAMES,产品铁律)。
- 落盘:promoted=True 才写 skills_root/<name>/SKILL.md(enabled: false 沿用 install 约定)。
- 任何异常(loop 炸 / runner 抛)→ 不晋升,不抛(失败诚实降级)。
- 不调真 worktree(测试桩,真集成留 v1.1)。
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from argos.skills_curator.index import BUILTIN_NAMES


@dataclass(frozen=True, slots=True)
class PromotionResult:
    """A/B 评估结果。"""

    promoted: bool
    reason: str
    a_passed: int = 0
    b_passed: int = 0
    a_total: int = 0
    b_total: int = 0


def _is_pass(pass_status: str | None) -> bool:
    """走 runner.PASS_PASSED 常量避免硬编码字符串(解耦)。"""
    try:
        from argos.eval.runner import PASS_PASSED
        return pass_status == PASS_PASSED
    except Exception:  # noqa: BLE001
        return pass_status == "passed"


def _skill_md_path_for(skills_root: Path, name: str) -> Path:
    return skills_root / name / "SKILL.md"


def _atomic_write_skill(skill_md: Path, content: str) -> None:
    """原子写(同 install 约定:写 .tmp 后 rename,失败时旧文件完整)。

    tmp 名带 pid+uuid(review#4):CLI 与 daemon 并发晋升同名技能时,确定性
    .tmp 后缀会互相覆盖 → 撕裂写。replace 仍原子(同目录 rename)。
    """
    import os
    import uuid

    skill_md.parent.mkdir(parents=True, exist_ok=True)
    tmp = skill_md.with_name(
        f"{skill_md.name}.{os.getpid()}.{uuid.uuid4().hex}.tmp")
    tmp.write_text(content, encoding="utf-8")
    tmp.replace(skill_md)


def _rebuild_index(skills_root: Path) -> None:
    """重新扫描本地 skills 目录,刷新 in-memory index(让 daemon 后续能发现)。

    不调 skills_curator.index.fetch_remote(避免网络);仅触发一次 load_cache 让 index
    反映本地落盘。失败静默 —— 落盘已成功,index 刷新是 best-effort。
    """
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
        if in_fm and stripped == "enabled: false":
            out.append(line.replace("enabled: false", "enabled: true", 1))
        else:
            out.append(line)
        if fence_seen >= 2:
            in_fm = False
    return "".join(out)


def promote(
    *,
    candidate: Any,      # SkillCandidate
    tasks: list,         # list[EvalTask]
    runner: Any,         # A 侧 runner;必有 .run(task, *, model_tier) -> EvalResult
    runner_b: Any = None,  # B 侧 runner(None → 与 A 侧共用同一 runner)
    skills_root: Path,
) -> PromotionResult:
    """A/B 评估 + 晋升。绝不抛(失败静默 → promoted=False)。

    runner_b 为 None 时 B 侧与 A 侧共用 runner(向后兼容)。
    落盘前检查同名覆盖:非学习产物(无 source_run 标记)→ 拒绝,学习产物 → 允许覆盖。
    """
    import logging as _log
    log = _log.getLogger(__name__)

    name = getattr(candidate, "name", "")
    body = getattr(candidate, "body_markdown", "")
    if not name or not body:
        return PromotionResult(promoted=False, reason="candidate_empty")

    # 1. builtin 硬拒(产品铁律)
    if name in BUILTIN_NAMES:
        return PromotionResult(
            promoted=False, reason=f"builtin_protected:{name}",
        )

    # 2. 同名覆盖防护(A/B 之前检查,避免无意义计算)
    skill_md = _skill_md_path_for(skills_root, name)
    if skill_md.exists():
        try:
            existing = skill_md.read_text(encoding="utf-8")
            # 只检查 YAML frontmatter 块(首尾 "---" 之间)避免正文示例代码误判。
            # 提取:按行分割,收集第一个 "---" 到第二个 "---" 之间的行,join 后检查。
            lines = existing.splitlines()
            # B2 修复:文件首行不是 "---" → 无 YAML frontmatter,直接视为非学习产物。
            # 不以首行为准会被 Markdown 水平分割线(---) + 正文 source_run: 内容欺骗。
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
            # 用户/社区技能,保守拒绝,原文件不动
            return PromotionResult(
                promoted=False, reason=f"name_collision:{name}",
            )
        # 学习产物(含 source_run 标记)→ 允许覆盖(整合更新)
        log.info("promote: overwriting existing learned skill %r", name)

    # 3. A/B 跑(同 model_tier,本函数不感知 hint —— 那是 runner/loop_factory 的事)
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

    # 3b. 严格提升才晋升
    if b_passed <= a_passed:
        return PromotionResult(
            promoted=False,
            reason=f"no_improvement(a={a_passed}/{a_total},b={b_passed}/{b_total})",
            a_passed=a_passed, b_passed=b_passed,
            a_total=a_total, b_total=b_total,
        )

    # 4. 落盘(auto-enable: A/B gate is the quality bar; no extra human step needed)
    enabled_body = _enable_in_body(body)
    try:
        _atomic_write_skill(skill_md, enabled_body)
    except Exception as e:  # noqa: BLE001
        return PromotionResult(
            promoted=False, reason=f"write_failed:{type(e).__name__}:{e}",
            a_passed=a_passed, b_passed=b_passed,
            a_total=a_total, b_total=b_total,
        )

    # 5. best-effort 刷 index(失败不阻断)
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
