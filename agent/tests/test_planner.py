"""planner 拆活测试 —— M3 强模型 + 剥 <think> 块 + lenient JSON 提取(探针已证)。"""
import pytest

from argos_agent import planner
from argos_agent.plan_schema import PlanSpec, PlannerError


class _FakeChoice:
    def __init__(self, content): self.message = type("M", (), {"content": content})()


def _patch_chat(monkeypatch, responses):
    """monkeypatch planner._chat 返回 responses 列表(每次调一个)。"""
    iter_resp = iter(responses)
    def fake_chat(messages, model, temperature, max_tokens):
        try:
            return next(iter_resp)
        except StopIteration:
            raise AssertionError("planner._chat called more times than stubbed responses")
    monkeypatch.setattr(planner, "_chat", fake_chat)


def test_planner_parses_clean_json(monkeypatch):
    txt = '{"tasks": [{"goal": "扫仓库", "verify_cmd": "grep -rn x ."}, {"goal": "改写", "verify_cmd": "pytest -q"}]}'
    _patch_chat(monkeypatch, [_FakeChoice(txt)])
    spec = planner.planner_llm(goal="把 x 改 y")
    assert isinstance(spec, PlanSpec)
    assert len(spec.tasks) == 2
    assert spec.tasks[0].goal == "扫仓库"


def test_planner_strips_think_block_and_extracts_json(monkeypatch):
    """M3 是推理模型,默认带 <think>...</think> 块 —— 探针铁证。"""
    txt = (
        "<think>\nLet me think...\n</think>\n"
        "```json\n"
        '{"tasks": [{"goal": "扫", "verify_cmd": "grep -rn x ."}, {"goal": "改", "verify_cmd": "pytest"}]}\n'
        "```"
    )
    _patch_chat(monkeypatch, [_FakeChoice(txt)])
    spec = planner.planner_llm(goal="any")
    assert len(spec.tasks) == 2
    assert spec.tasks[0].goal == "扫"


def test_planner_bad_json_raises_planner_error(monkeypatch):
    """返坏 JSON → 抛 PlannerError(不让流到 worker,spec §4.3 红线)。"""
    _patch_chat(monkeypatch, [_FakeChoice("完全没 JSON,纯聊天内容")])
    with pytest.raises(PlannerError):
        planner.planner_llm(goal="any")


def test_planner_truncates_over_max_tasks(monkeypatch):
    """返 6 摊 → 截断到 5(spec §5 范围 2-5 摊,max=5 是硬上限)。"""
    tasks_json = ",".join(
        f'{{"goal": "t{i}", "verify_cmd": "echo {i}"}}' for i in range(6)
    )
    _patch_chat(monkeypatch, [_FakeChoice(f'{{"tasks": [{tasks_json}]}}')])
    spec = planner.planner_llm(goal="any")
    assert len(spec.tasks) == 5  # 截断


def test_planner_truncates_under_min_tasks_raises(monkeypatch):
    """返 1 摊 → PlanSpec 兜型拒(min_length=2)。"""
    _patch_chat(monkeypatch, [_FakeChoice('{"tasks": [{"goal": "only", "verify_cmd": "x"}]}')])
    with pytest.raises(PlannerError):
        planner.planner_llm(goal="any")
