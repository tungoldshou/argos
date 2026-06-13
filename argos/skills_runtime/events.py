"""Skill run lifecycle events(spec §2.2 / §10.1)。

事件约定(任务:6 个 events.py 一致性):
- 复用 `argos.protocol.events.EventBus`(全局唯一总线;本模块不重新定义)
- 每个事件 dataclass 含 `kind` 类属性(类名 snake_case;EventBus 路由 + replay 依赖)
- `kind` 不参与 dataclass 字段;`asdict()` 不序列化它
- 注:本模块用 `kind: ClassVar[str] = "..."` 类型注解式定义(其他 4 个文件用
  `kind = "..."` 赋值式);两者运行时等价(`cls.kind` 都拿得到)—— ClassVar 写法
  更显式说明"这是类级常量",保留以提示类型意图。

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
