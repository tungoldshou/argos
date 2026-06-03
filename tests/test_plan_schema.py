"""PlanSpec 硬契约 —— planner 拆活的输出形状 + PlannerError 显式错误。"""
import pytest
from pydantic import ValidationError

from argos_agent.plan_schema import PlanSpec, PlanTask, PlannerError


def test_plan_task_minimal():
    t = PlanTask(goal="扫仓库", verify_cmd="grep -rn 'xxx' .")
    assert t.goal == "扫仓库" and t.verify_cmd == "grep -rn 'xxx' ."
    assert t.task_id  # 自动生成


def test_plan_task_requires_goal_and_verify_cmd():
    with pytest.raises(ValidationError):
        PlanTask(goal="", verify_cmd="x")  # 空 goal 拒
    with pytest.raises(ValidationError):
        PlanTask(goal="x", verify_cmd="")  # 空 verify 拒


def test_plan_spec_accepts_valid_tasks():
    spec = PlanSpec(tasks=[
        PlanTask(goal="扫", verify_cmd="grep -rn 'x' ."),
        PlanTask(goal="改", verify_cmd="pytest -q"),
    ])
    assert len(spec.tasks) == 2
    assert spec.tasks[0].task_id != spec.tasks[1].task_id


def test_plan_spec_rejects_empty():
    with pytest.raises(ValidationError):
        PlanSpec(tasks=[])


def test_planner_error_distinct_from_validation():
    assert issubclass(PlannerError, Exception)
    # PlannerError 跟 pydantic ValidationError 区分(下游 fan_out 显式捕)
    from pydantic import ValidationError as _VE
    assert not issubclass(PlannerError, _VE)
