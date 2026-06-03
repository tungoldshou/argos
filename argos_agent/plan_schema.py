"""planner 拆活的硬契约 schema(spec §4.3 红线兑现:planner schema 不是 prompt 文本)。

PlanTask 每条含 id(auto)/goal/verify_cmd——
planner 拆出来 → pydantic 兜型 → 任何错型抛 PlannerError → 不让坏 JSON 流到 worker。
"""
from __future__ import annotations

import uuid
from typing import List

from pydantic import BaseModel, Field, field_validator


class PlannerError(RuntimeError):
    """planner 拆活或解析失败。orchestrator 据此 escalate,不流到 worker。"""


class PlanTask(BaseModel):
    """一个可独立验证的子任务。"""
    task_id: str = Field(default_factory=lambda: uuid.uuid4().hex[:12])
    goal: str = Field(min_length=1, description="一个具体到 agent 可执行的子目标")
    verify_cmd: str = Field(min_length=1, description="该 task 完成后跑哪条命令验证(白名单由 worker run_command 端守)")

    @field_validator("goal", "verify_cmd")
    @classmethod
    def _strip(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("must be non-empty after strip")
        return v


class PlanSpec(BaseModel):
    """planner 一次拆出来的全部子任务。2-5 摊(spec §5 范围)。"""
    tasks: List[PlanTask] = Field(min_length=2, max_length=5)
