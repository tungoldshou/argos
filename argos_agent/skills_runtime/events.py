"""Skill run lifecycle events(spec §2.2 / §10.1)。

- SkillRunStart:skill run 起始时投(对位 LspServerEvent.spawn / HookFired.pre)。
- SkillRunEnd:skill run 结束时投(对位 LspServerEvent.ready / crash)。

两个 event 投到 EventBus → 持久化 events.jsonl + 活动栏 "Skill" 区段渲染。
**start + end 分两类**:start 是进入信号(显 "started"),end 是结果信号
(显 verdict + 耗时);1:1 配对(用 run_id 关联,本期 v1 仅靠顺序)。"""
from __future__ import annotations

from dataclasses import dataclass
from typing import ClassVar, Literal, Mapping


Verdict = Literal["passed", "failed", "partial", "n_a", "skipped"]


@dataclass(frozen=True, slots=True)
class SkillRunStart:
    """skill run 起始信号(对位 LspServerEvent.spawn)。"""
    kind: ClassVar[str] = "skill_run_start"
    skill_name: str
    args: Mapping[str, object]
    cwd: str = ""
    timestamp_ms: int = 0


@dataclass(frozen=True, slots=True)
class SkillRunEnd:
    """skill run 结束信号(对位 LspServerEvent.ready / crash)。"""
    kind: ClassVar[str] = "skill_run_end"
    skill_name: str
    verdict: Verdict
    duration_ms: int
    finding_count: int
    error_count: int
    cwd: str = ""
    timestamp_ms: int = 0
