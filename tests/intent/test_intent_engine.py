"""IntentEngine 测试套件(设计 §7 + §2.4)。

测试矩阵：
    1. 明确目标 → 0 问直出(confirmation_required=False)
    2. 模糊目标 → ≤3 问，confirmation_required=True
    3. 高风险词表逐词抽测 → risk_flags + confirmation_required=True
    4. 模型吐垃圾 JSON → fail-closed 降级(goal=原话)
    5. render_confirmation 含 not_doing 与风险标签
    6. questions 最多 3 个
    7. 模型异常 → fail-closed 降级
    8. 模型吐缺字段 JSON → fail-closed 降级
    9. 模型吐 markdown 包裹的 JSON → 正常解析
    10. IntentCard 是 frozen dataclass（不可变）
"""
from __future__ import annotations

import json
import pytest

from argos_agent.intent.card import IntentCard
from argos_agent.intent.engine import IntentEngine


# ─── FakeModel ─────────────────────────────────────────────────────────────────

class FakeModel:
    """按脚本逐次 stream text。与 ModelClient.stream duck-type 同构。"""

    def __init__(self, scripts: list[str]) -> None:
        self._scripts = scripts
        self._i = 0

    async def stream(self, messages, *, system, system_dynamic=None):
        text = self._scripts[min(self._i, len(self._scripts) - 1)]
        self._i += 1
        for ch in text:
            yield ch


def _make_json(
    goal: str = "执行某个任务",
    deliverable: str = "任务结果",
    constraints: list[str] | None = None,
    not_doing: list[str] | None = None,
    questions: list[str] | None = None,
) -> str:
    return json.dumps({
        "goal": goal,
        "deliverable": deliverable,
        "constraints": constraints or [],
        "not_doing": not_doing or [],
        "questions": questions or [],
    }, ensure_ascii=False)


# ─── 1. 明确目标直出 ───────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_clear_intent_no_confirmation():
    """明确目标 + 0 问 → confirmation_required=False 直出。"""
    resp = _make_json(
        goal="统计 src/ 目录下所有 Python 文件的行数并输出汇总表",
        deliverable="命令行输出的汇总表",
        questions=[],
    )
    engine = IntentEngine()
    card = await engine.parse("统计 src/ 目录下所有 Python 文件的行数并输出汇总表", FakeModel([resp]))
    assert not card.confirmation_required
    assert card.goal == "统计 src/ 目录下所有 Python 文件的行数并输出汇总表"
    assert card.questions == ()
    assert card.risk_flags == ()


# ─── 2. 模糊目标 → 有问题 ──────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_vague_intent_has_questions():
    """模糊 utterance → 模型问 ≤3 个澄清问，confirmation_required=True。"""
    resp = _make_json(
        goal="做某件事",
        deliverable="某个产物",
        questions=["你想要什么格式的输出？", "需要覆盖哪些目录？"],
    )
    engine = IntentEngine()
    card = await engine.parse("帮我做一下", FakeModel([resp]))
    assert card.confirmation_required
    assert 1 <= len(card.questions) <= 3


@pytest.mark.asyncio
async def test_vague_short_utterance_triggers_confirmation():
    """极短 utterance（≤5字符）即使模型不问也触发确认。"""
    resp = _make_json(goal="未知任务", deliverable="", questions=[])
    engine = IntentEngine()
    card = await engine.parse("帮我", FakeModel([resp]))
    assert card.confirmation_required


# ─── 3. 高风险词表 ──────────────────────────────────────────────────────────────

@pytest.mark.asyncio
@pytest.mark.parametrize("utterance, expected_flag", [
    ("请帮我删除 /tmp/old_logs 目录", "delete_files"),
    ("把 build/ 清空", "delete_files"),
    ("remove all temp files", "delete_files"),
    ("delete the cache folder", "delete_files"),
    ("转账给张三 500 元", "financial_transfer"),
    ("给供应商付款", "financial_transfer"),
    ("transfer $100 to account", "financial_transfer"),
    ("发邮件给全组", "send_email"),
    ("发送通知给所有用户", "send_message"),
    ("send an email to the team", "send_email"),
    ("购买 10 个域名", "purchase"),
    ("下单买两台服务器", "purchase"),
    ("卸载 Python", "uninstall"),
    ("格式化这个 U 盘", "format_disk"),
    ("format the disk", "format_disk"),
])
async def test_risk_words_trigger_flag(utterance: str, expected_flag: str):
    """高风险词命中 → risk_flags 含对应标签 + confirmation_required=True。"""
    resp = _make_json(goal=utterance, deliverable="", questions=[])
    engine = IntentEngine()
    card = await engine.parse(utterance, FakeModel([resp]))
    assert expected_flag in card.risk_flags, (
        f"utterance={utterance!r} 期望 risk_flag={expected_flag!r}，实得 {card.risk_flags}"
    )
    assert card.confirmation_required


# ─── 4. 模型吐垃圾 JSON → fail-closed 降级 ─────────────────────────────────────

@pytest.mark.asyncio
async def test_garbage_json_failclosed():
    """模型返回无效 JSON → goal=原话，confirmation_required=True，questions 为空。"""
    engine = IntentEngine()
    utterance = "帮我整理一下代码"
    card = await engine.parse(utterance, FakeModel(["这不是 JSON {{{{{bad"]))
    assert card.goal == utterance
    assert card.confirmation_required
    assert card.questions == ()


@pytest.mark.asyncio
async def test_empty_response_failclosed():
    """模型返回空字符串 → fail-closed 降级。"""
    engine = IntentEngine()
    utterance = "优化数据库查询"
    card = await engine.parse(utterance, FakeModel([""]))
    assert card.goal == utterance
    assert card.confirmation_required


# ─── 5. render_confirmation 含 not_doing 与风险标签 ───────────────────────────

def test_render_confirmation_contains_not_doing():
    """render_confirmation 输出含 not_doing 描述。"""
    card = IntentCard(
        utterance="删除旧日志",
        goal="删除 /var/log/ 下 30 天前的日志文件",
        deliverable="释放磁盘空间",
        constraints=(),
        not_doing=("不删除当天日志", "不影响正在运行的服务"),
        risk_flags=("delete_files",),
        confirmation_required=True,
        questions=(),
    )
    rendered = IntentEngine.render_confirmation(card)
    assert "不删除当天日志" in rendered
    assert "不影响正在运行的服务" in rendered
    assert "delete_files" in rendered
    assert "对吗？" in rendered


def test_render_confirmation_risk_flags_explicit():
    """render_confirmation 显式列出所有风险标签。"""
    card = IntentCard(
        utterance="转账并发邮件",
        goal="转账 1000 元并发确认邮件",
        deliverable="转账收据 + 邮件发送成功",
        constraints=(),
        not_doing=(),
        risk_flags=("financial_transfer", "send_email"),
        confirmation_required=True,
        questions=(),
    )
    rendered = IntentEngine.render_confirmation(card)
    assert "financial_transfer" in rendered
    assert "send_email" in rendered


def test_render_confirmation_no_risk_no_warning():
    """无风险标签 → render 不含风险警告行。"""
    card = IntentCard(
        utterance="列出文件",
        goal="列出当前目录所有文件",
        deliverable="文件列表",
        constraints=(),
        not_doing=(),
        risk_flags=(),
        confirmation_required=False,
        questions=(),
    )
    rendered = IntentEngine.render_confirmation(card)
    assert "⚠️" not in rendered
    assert "检测到高风险" not in rendered
    assert "我理解你要：列出当前目录所有文件" in rendered


# ─── 6. questions 最多 3 个 ────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_questions_capped_at_three():
    """模型给出超过 3 个问题 → IntentCard.questions 最多 3 个。"""
    resp = _make_json(
        goal="做很多事",
        deliverable="结果",
        questions=["问1？", "问2？", "问3？", "问4？", "问5？"],
    )
    engine = IntentEngine()
    card = await engine.parse("做很多事", FakeModel([resp]))
    assert len(card.questions) <= 3


# ─── 7. 模型异常 → fail-closed 降级 ───────────────────────────────────────────

@pytest.mark.asyncio
async def test_model_exception_failclosed():
    """模型 stream 抛出异常 → fail-closed 降级（goal=原话）。"""

    class BrokenModel:
        async def stream(self, messages, *, system, system_dynamic=None):
            raise RuntimeError("网络超时")
            yield  # noqa: unreachable — 使生成器语法合法

    engine = IntentEngine()
    utterance = "重构认证模块"
    card = await engine.parse(utterance, BrokenModel())
    assert card.goal == utterance
    assert card.confirmation_required


# ─── 8. 缺字段 JSON → fail-closed 降级 ─────────────────────────────────────────

@pytest.mark.asyncio
async def test_missing_field_json_failclosed():
    """模型返回缺少必须字段的 JSON → fail-closed 降级。"""
    # 缺少 "not_doing" 字段
    incomplete = json.dumps({"goal": "做某事", "deliverable": "结果", "constraints": [], "questions": []})
    engine = IntentEngine()
    utterance = "帮我做某事"
    card = await engine.parse(utterance, FakeModel([incomplete]))
    assert card.goal == utterance
    assert card.confirmation_required


@pytest.mark.asyncio
async def test_empty_goal_json_failclosed():
    """模型返回 goal 为空字符串的 JSON → fail-closed 降级。"""
    resp = _make_json(goal="", deliverable="结果")
    engine = IntentEngine()
    utterance = "优化代码"
    card = await engine.parse(utterance, FakeModel([resp]))
    assert card.goal == utterance
    assert card.confirmation_required


# ─── 9. markdown 包裹 JSON → 正常解析 ────────────────────────────────────────────

@pytest.mark.asyncio
async def test_markdown_wrapped_json_parsed():
    """模型返回 ```json 包裹的 JSON → 正常解析不降级。"""
    inner = _make_json(
        goal="列出所有 Python 测试文件",
        deliverable="文件路径列表",
        questions=[],
    )
    wrapped = f"```json\n{inner}\n```"
    engine = IntentEngine()
    card = await engine.parse("列出所有 Python 测试文件", FakeModel([wrapped]))
    assert card.goal == "列出所有 Python 测试文件"
    assert not card.confirmation_required


# ─── 10. IntentCard 不可变 ─────────────────────────────────────────────────────

def test_intent_card_is_frozen():
    """IntentCard 是 frozen dataclass，不允许赋值修改。"""
    card = IntentCard(
        utterance="test",
        goal="test goal",
    )
    with pytest.raises((AttributeError, TypeError)):
        card.goal = "modified"  # type: ignore[misc]


# ─── 11. render_confirmation 含 goal 主目标 ─────────────────────────────────────

def test_render_confirmation_contains_goal():
    """render_confirmation 输出中第一行即含目标描述。"""
    card = IntentCard(
        utterance="统计代码行数",
        goal="统计 src/ 下所有文件的代码行数",
        deliverable="汇总表",
    )
    rendered = IntentEngine.render_confirmation(card)
    assert "统计 src/ 下所有文件的代码行数" in rendered
    assert "汇总表" in rendered


# ─── 12. risk_flags 去重 ──────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_risk_flags_deduplicated():
    """多个同义词命中同一 flag → risk_flags 中该 flag 只出现一次。"""
    resp = _make_json(goal="删除所有文件", deliverable="空目录", questions=[])
    utterance = "删除并清空所有文件"  # "删除" + "清空" 都映射 delete_files
    engine = IntentEngine()
    card = await engine.parse(utterance, FakeModel([resp]))
    assert card.risk_flags.count("delete_files") == 1


# ─── 13. 正常意图 constraints/not_doing 正确传递 ─────────────────────────────────

@pytest.mark.asyncio
async def test_constraints_and_not_doing_passed_through():
    """模型返回的 constraints 和 not_doing 正确映射到 IntentCard。"""
    resp = _make_json(
        goal="重命名所有 .log 文件",
        deliverable="重命名后的文件列表",
        constraints=["只处理 30 天前的文件"],
        not_doing=["不删除任何文件", "不影响 .txt 文件"],
        questions=[],
    )
    engine = IntentEngine()
    card = await engine.parse("重命名旧日志文件", FakeModel([resp]))
    assert "只处理 30 天前的文件" in card.constraints
    assert "不删除任何文件" in card.not_doing
    assert "不影响 .txt 文件" in card.not_doing
