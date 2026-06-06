"""契约层分类器测试 —— 守住"结构化才注入契约"的边界(实测:非结构化注入有害)。

分类错 = 用错契约/给写作硬塞契约 = 护城河白搭甚至反效果。纯逻辑,快。
"""
import pytest

from argos_agent.contracts import classify, contract_for


@pytest.mark.parametrize("goal,expected", [
    ("设计一个 TODO REST API,3 个端点", "rest-api"),
    ("design a REST API with pagination endpoints", "rest-api"),
    ("用户表的数据库 schema 与外键", "db-schema"),
    ("create a database table migration", "db-schema"),
    ("订单状态机:状态枚举与流转规则", "state-machine"),
    ("a login workflow state machine", "state-machine"),
    ("应用的配置文件结构与环境变量", "config"),
    ("define the config yaml settings", "config"),
])
def test_classify_structured_domains(goal, expected):
    assert classify(goal) == expected


@pytest.mark.parametrize("goal", [
    "写一篇关于 AI 的文章",
    "write a blog post comparing tools",
    "总结这份报告的要点",
    "analyze the market trends",
    "讲个故事",
])
def test_non_structured_returns_none(goal):
    # 非结构化(写作/分析)绝不注入契约 —— 实测有害(15>10)。
    assert classify(goal) == "none"
    dom, contract = contract_for(goal)
    assert dom == "none"
    assert contract is None


def test_generic_for_field_level_engineering():
    # 含字段/类型/模型等工程信号但无明确领域 → generic 结构化。
    assert classify("实现一个带 id 字段和 status 枚举的数据模型") == "generic"


def test_contract_injected_for_structured():
    dom, contract = contract_for("设计一个 REST API 接口")
    assert dom == "rest-api"
    assert contract is not None
    assert "C10" in contract  # 关键的对齐自检条款在


def test_plain_chitchat_no_contract():
    # 纯闲聊不该被当结构化。
    dom, contract = contract_for("你好,今天天气怎么样")
    assert dom == "none"
    assert contract is None
