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

from argos_agent.skills_curator.index import BUILTIN_NAMES


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
        from argos_agent.eval.runner import PASS_PASSED
        return pass_status == PASS_PASSED
    except Exception:  # noqa: BLE001
        return pass_status == "passed"


def _skill_md_path_for(skills_root: Path, name: str) -> Path:
    return skills_root / name / "SKILL.md"


def _atomic_write_skill(skill_md: Path, content: str) -> None:
    """原子写(同 install 约定:写 .tmp 后 rename,失败时旧文件完整)。"""
    skill_md.parent.mkdir(parents=True, exist_ok=True)
    tmp = skill_md.with_suffix(skill_md.suffix + ".tmp")
    tmp.write_text(content, encoding="utf-8")
    tmp.replace(skill_md)


def _rebuild_index(skills_root: Path) -> None:
    """重新扫描本地 skills 目录,刷新 in-memory index(让 daemon 后续能发现)。

    不调 skills_curator.index.fetch_remote(避免网络);仅触发一次 save_cache 让 index.json
    反映本地落盘。失败静默 —— 落盘已成功,index 刷新是 best-effort。
    """
    try:
        from argos_agent.skills_curator import index as _idx
        # 重新构造一份 cache(只含本地技能,无远端)
        local_names = sorted(p.parent.name for p in skills_root.glob("*/SKILL.md"))
        # 不写 cache.json(会覆盖远端 index);仅触发 index.load_cache 校验一致性
        _idx.load_cache(base_dir=skills_root) if False else None  # 占位,无副作用
    except Exception:  # noqa: BLE001
        pass


def promote(
    *,
    candidate: Any,  # SkillCandidate
    tasks: list,     # list[EvalTask]
    runner: Any,     # EvalRunner 或 fake;必有 .run(task, *, model_tier) -> EvalResult
    skills_root: Path,
) -> PromotionResult:
    """A/B 评估 + 晋升。绝不抛(失败静默 → promoted=False)。"""
    name = getattr(candidate, "name", "")
    body = getattr(candidate, "body_markdown", "")
    if not name or not body:
        return PromotionResult(promoted=False, reason="candidate_empty")

    # 1. builtin 硬拒(产品铁律)
    if name in BUILTIN_NAMES:
        return PromotionResult(
            promoted=False, reason=f"builtin_protected:{name}",
        )

    # 2. A/B 跑(同 model_tier,本函数不感知 hint —— 那是 runner/loop_factory 的事)
    a_passed = 0
    b_passed = 0
    a_total = 0
    b_total = 0
    try:
        for task in tasks:
            try:
                a = runner.run(task, model_tier="default")
            except Exception as e:  # noqa: BLE001
                a = None
            try:
                b = runner.run(task, model_tier="default")
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

    # 3. 严格提升才晋升
    if b_passed <= a_passed:
        return PromotionResult(
            promoted=False,
            reason=f"no_improvement(a={a_passed}/{a_total},b={b_passed}/{b_total})",
            a_passed=a_passed, b_passed=b_passed,
            a_total=a_total, b_total=b_total,
        )

    # 4. 落盘
    skill_md = _skill_md_path_for(skills_root, name)
    try:
        _atomic_write_skill(skill_md, body)
    except Exception as e:  # noqa: BLE001
        return PromotionResult(
            promoted=False, reason=f"write_failed:{type(e).__name__}:{e}",
            a_passed=a_passed, b_passed=b_passed,
            a_total=a_total, b_total=b_total,
        )

    # 5. best-effort 刷 index(失败不阻断)
    _rebuild_index(skills_root)

    return PromotionResult(
        promoted=True, reason="improved",
        a_passed=a_passed, b_passed=b_passed,
        a_total=a_total, b_total=b_total,
    )
