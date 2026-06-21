"""AnalysisSkill 数据契约(spec §2.2)。

- `AnalysisSkill` / `AnalysisSkillResult` / `Finding` 全部 frozen dataclass。
- **重命名避撞** `argos/skills.py:24` 的 `Skill`(markdown 库,非 runtime)。
- verdict 5 态:passed / failed / partial / n_a / skipped(spec §2.2 / §3)。
- findings / errors 走 tuple(不可变 + 哈希 + frozen 友好)。
- severity 3 态:error / warning / info(security context:error = 假绿禁区,见 D5)。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Awaitable, Callable, Literal, Mapping, TYPE_CHECKING

from argos.i18n import t

if TYPE_CHECKING:
    from argos.core.loop import LoopState  # noqa: F401


# severity 仅 3 态(spec §2.2):error = 必修;warning = 应看;info = 观察
Severity = Literal["error", "warning", "info"]
_SEV_VALUES: frozenset[str] = frozenset({"error", "warning", "info"})

# verdict 5 态(spec §2.2):passed 全过;failed 有 error finding;partial 部分跑; n_a 没法跑;skipped 用户取消/timeout
Verdict = Literal["passed", "failed", "partial", "n_a", "skipped"]
_VERDICT_VALUES: frozenset[str] = frozenset({"passed", "failed", "partial", "n_a", "skipped"})

# 9 个 category(spec §2.4 / §2.5):secret / dep_vuln / dep_audit / permission /
# duplicate / complexity / dead_code / verify / config
_CATEGORY_VALUES: frozenset[str] = frozenset({
    "secret", "dep_vuln", "dep_audit", "permission",
    "duplicate", "complexity", "dead_code", "verify", "config",
})


@dataclass(frozen=True, slots=True)
class Finding:
    """单条分析 finding(spec §2.2)。
    severity / category 受 Literal 校验;snippet 长度上限 120 防 token 暴。"""
    severity: Severity
    category: str
    message: str
    file: str | None = None
    line: int | None = None
    snippet: str | None = None
    suggestion: str | None = None

    def __post_init__(self) -> None:
        if self.severity not in _SEV_VALUES:
            raise ValueError(t("skill.finding_severity_invalid", valid=_SEV_VALUES, value=self.severity))
        if self.snippet is not None and len(self.snippet) > 120:
            raise ValueError(t("skill.finding_snippet_too_long", length=len(self.snippet)))


@dataclass(frozen=True, slots=True)
class AnalysisSkillContext:
    """skill run 上下文(spec §2.2)。
    - workspace:Path  —— 走 host Seatbelt 文件访问边界
    - approval_level:str  —— observe / propose / confirm / auto(spec D13 4 档拨盘)
    - run_id:str  —— 关联 SkillRunStart / SkillRunEnd
    - loop:LoopState | None  —— 透传(本期 v1 简化:暂未使用,v1.1 接 run working set)"""
    workspace: Path
    approval_level: str
    run_id: str
    loop: "LoopState | None" = None


@dataclass(frozen=True, slots=True)
class AnalysisSkillResult:
    """skill run 结果(spec §2.2)。frozen;findings / errors 走 tuple(不可变)。"""
    summary: str
    findings: tuple[Finding, ...]
    duration_ms: int
    errors: tuple[str, ...]
    verdict: Verdict
    raw: Mapping[str, object] | None = None

    def __post_init__(self) -> None:
        if self.verdict not in _VERDICT_VALUES:
            raise ValueError(t("skill.result_verdict_invalid", valid=_VERDICT_VALUES, value=self.verdict))
        if self.duration_ms < 0:
            raise ValueError(t("skill.result_duration_negative", value=self.duration_ms))


# skill run 函数签名:run(args: dict, ctx: AnalysisSkillContext) -> AnalysisSkillResult
AnalysisSkillRun = Callable[[Mapping[str, object], AnalysisSkillContext], Awaitable[AnalysisSkillResult]]


@dataclass(frozen=True, slots=True)
class AnalysisSkill:
    """注册到 SkillRegistry 的单条 skill(spec §2.2)。
    name 必含 ASCII 字母数字 + _ + -(防注入 / 匹配 dispatch 白名单)。"""
    name: str
    description: str
    parameters_schema: Mapping[str, object]
    run: AnalysisSkillRun
    requires_approval: bool

    def __post_init__(self) -> None:
        if not self.name or not all(c.isascii() and (c.isalnum() or c in "_-") for c in self.name):
            raise ValueError(t("skill.name_invalid", name=self.name))
