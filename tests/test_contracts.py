"""Internal documentation."""
import pytest

from argos.contracts import classify, contract_for


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
    assert classify(goal) == "none"
    dom, contract = contract_for(goal)
    assert dom == "none"
    assert contract is None


def test_generic_for_field_level_engineering():
    assert classify("实现一个带 id 字段和 status 枚举的数据模型") == "generic"


def test_contract_injected_for_structured():
    dom, contract = contract_for("设计一个 REST API 接口")
    assert dom == "rest-api"
    assert contract is not None
    assert "C10" in contract


def test_plain_chitchat_no_contract():
    dom, contract = contract_for("你好,今天天气怎么样")
    assert dom == "none"
    assert contract is None
