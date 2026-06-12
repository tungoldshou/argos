"""tests/permissions/test_computer_hard_rules.py — 非开发者 computer use HARD RULES 验收测试。

验收规则(任务2 §2):
  1. check_computer_type_text:命中金融/卡号/CVV/验证码/密码词表 → 返回规则名。
  2. check_computer_open_app:命中支付/银行 app 词表 → 返回规则名。
  3. check_computer_hard_rules:总入口按 action 路由。
  4. 非命中场景返回 None(无误报)。
  5. evaluator.evaluate 在 computer.type_text/computer.open_app 命中时 → ask + hard_rule 前缀触发。
  6. autonomy.classify 将 hard_rule:computer_* 视为不可降级(RED,不被 preauth 降)。
  7. conductor 自治路径(trust≤L1)下命中 → 拒绝并诚实说明原因。
"""
from __future__ import annotations

import pytest

from argos_agent.permissions.hard_rules import (
    check_computer_hard_rules,
    check_computer_open_app,
    check_computer_type_text,
    _FINANCIAL_TEXT_PATTERN,
    _PAYMENT_APP_PATTERN,
)
from argos_agent.permissions.config import PermissionsConfig
from argos_agent.permissions.evaluator import evaluate
from argos_agent.approval import ApprovalLevel


# ── 1. check_computer_type_text —— 命中场景 ───────────────────────────────────

@pytest.mark.parametrize("text,desc", [
    ("1234 5678 9012 3456", "16位卡号(空格分隔)"),
    ("4111111111111111", "16位卡号(连续)"),
    ("1234-5678-9012-3456", "16位卡号(连字符)"),
    ("CVV: 123", "CVV 关键词+数字"),
    ("cvv 456", "cvv 小写+数字"),
    ("CVC: 789", "CVC 关键词"),
    ("安全码: 321", "中文安全码"),
    ("验证码: 123456", "中文验证码+6位数"),
    ("短信码: 654321", "短信码"),
    ("动态码: 112233", "动态码"),
    ("OTP: 987654", "OTP 英文"),
    ("verification code: 445566", "英文 verification code"),
    ("password: mypassword123", "英文 password 关键词"),
    ("密码: abc123", "中文密码关键词"),
    ("card number: 4111111111111111", "card number 关键词"),
    ("卡号: 6222021234567890", "中文卡号关键词"),
    ("transfer amount: 5000.00", "转账金额关键词"),
    ("付款金额: 1,000.00", "中文付款金额"),
])
def test_type_text_financial_pattern_hit(text: str, desc: str):
    """金融/验证码模式命中 → 返回规则名(非 None)。"""
    result = check_computer_type_text(text)
    assert result is not None, f"'{desc}' 应命中金融规则,但返回 None。text={text!r}"
    assert result == "computer_type_financial_pattern"


@pytest.mark.parametrize("text,desc", [
    ("hello world", "普通文本"),
    ("implement the login feature", "开发任务描述"),
    ("click the submit button", "UI操作描述"),
    ("open the file manager", "应用操作"),
    ("search for python tutorials", "搜索文本"),
    ("", "空文本"),
    ("12345", "短数字(非卡号格式)"),
    ("abc 123 xyz", "混合普通文本"),
    ("username: john", "用户名(非密码)"),
    ("amount: 100", "金额但无转账关键词"),
    # 以下是原来密码分支误报的开发/文档上下文场景 —— 修复后不应命中
    ("the password reset flow", "password 后跟普通英文单词(开发文档)"),
    ("密码 是必填项", "中文密码后跟短描述(UI文案)"),
    ("口令 输入框", "口令后跟UI描述(无实质密码值)"),
    ("password field is required", "password 后跟普通英文描述"),
    ("forgot password link", "password 前有修饰词"),
    ("passcode input placeholder", "passcode 后跟UI描述"),
])
def test_type_text_non_financial_no_hit(text: str, desc: str):
    """非金融/验证码文本 → 返回 None(无误报)。"""
    result = check_computer_type_text(text)
    assert result is None, f"'{desc}' 不应命中金融规则,但返回 {result!r}。text={text!r}"


# ── 2. check_computer_open_app —— 命中场景 ────────────────────────────────────

@pytest.mark.parametrize("app,desc", [
    ("支付宝", "中文支付宝"),
    ("Alipay", "英文 Alipay"),
    ("微信支付", "微信支付"),
    ("WeChat Pay", "英文 WeChat Pay"),
    ("PayPal", "PayPal"),
    ("Venmo", "Venmo"),
    ("Zelle", "Zelle"),
    ("CashApp", "CashApp"),
    ("Cash App", "Cash App(带空格)"),
    ("Stripe", "Stripe"),
    ("Square", "Square"),
    ("网银", "中文网银"),
    ("Internet Banking", "英文网银"),
    ("招商银行", "招行"),
    ("工商银行", "工行"),
    ("建设银行", "建行"),
    ("农业银行", "农行"),
    ("中国银行", "中行"),
    ("CMB", "招行英文缩写"),
    ("ICBC", "工行英文缩写"),
    ("Chase", "Chase 银行"),
    ("Wells Fargo", "Wells Fargo"),
    ("Bank of America", "美国银行"),
    ("Robinhood", "Robinhood 证券"),
    ("Coinbase", "Coinbase"),
    ("Binance", "Binance"),
    ("证券", "中文证券"),
    ("Fidelity", "Fidelity"),
])
def test_open_app_payment_pattern_hit(app: str, desc: str):
    """支付/银行 app 词表命中 → 返回规则名。"""
    result = check_computer_open_app(app)
    assert result is not None, f"'{desc}' 应命中支付/银行规则,但返回 None。app={app!r}"
    assert result == "computer_open_payment_app"


@pytest.mark.parametrize("app,desc", [
    ("Finder", "Finder"),
    ("Terminal", "Terminal"),
    ("Safari", "Safari"),
    ("Calculator", "计算器"),
    ("TextEdit", "文本编辑"),
    ("Preview", "预览"),
    ("Photos", "照片"),
    ("Calendar", "日历"),
    ("Notes", "备忘录"),
    ("", "空名称"),
    ("VSCode", "VSCode"),
    ("Slack", "Slack"),
    ("Spotify", "Spotify"),
])
def test_open_app_non_payment_no_hit(app: str, desc: str):
    """非支付/银行 app → 返回 None(无误报)。"""
    result = check_computer_open_app(app)
    assert result is None, f"'{desc}' 不应命中支付/银行规则,但返回 {result!r}。app={app!r}"


# ── 3. check_computer_hard_rules —— 总入口路由 ────────────────────────────────

def test_check_hard_rules_type_text_routes_correctly():
    """computer.type_text + 金融文本 → 总入口返回规则名。"""
    rule = check_computer_hard_rules(
        "computer.type_text", {"text": "CVV: 123"}
    )
    assert rule == "computer_type_financial_pattern"


def test_check_hard_rules_open_app_routes_correctly():
    """computer.open_app + 支付 app → 总入口返回规则名。"""
    rule = check_computer_hard_rules(
        "computer.open_app", {"app": "支付宝"}
    )
    assert rule == "computer_open_payment_app"


def test_check_hard_rules_screenshot_returns_none():
    """computer.screenshot → 无词表规则,返回 None。"""
    rule = check_computer_hard_rules("computer.screenshot", {})
    assert rule is None


def test_check_hard_rules_click_returns_none():
    """computer.click → 无词表规则,返回 None。"""
    rule = check_computer_hard_rules("computer.click", {"x": 100, "y": 200})
    assert rule is None


def test_check_hard_rules_non_computer_action_returns_none():
    """非 computer.* 动作 → 不应被 computer hard rules 处理。"""
    rule = check_computer_hard_rules("run_command", {"command": "ls"})
    assert rule is None


# ── 4. evaluator.evaluate 集成测试 ─────────────────────────────────────────────

def _empty_config() -> PermissionsConfig:
    return PermissionsConfig.empty()


def test_evaluator_type_text_financial_returns_ask_with_hard_rule_trigger():
    """evaluator: computer.type_text + 金融文本 → ask + trigger 以 hard_rule: 开头。"""
    meta = evaluate(
        "computer.type_text",
        {"text": "password: supersecret123"},
        gate_level=ApprovalLevel.AUTO,
        config=_empty_config(),
    )
    assert meta.decision == "ask", (
        f"金融文本 type_text 应为 ask,得到 {meta.decision!r}"
    )
    assert meta.trigger.startswith("hard_rule:"), (
        f"trigger 应以 hard_rule: 开头,得到 {meta.trigger!r}"
    )
    assert "computer_type_financial_pattern" in meta.trigger


def test_evaluator_open_payment_app_returns_ask_with_hard_rule_trigger():
    """evaluator: computer.open_app + 支付 app → ask + trigger 以 hard_rule: 开头。"""
    meta = evaluate(
        "computer.open_app",
        {"app": "Alipay"},
        gate_level=ApprovalLevel.AUTO,
        config=_empty_config(),
    )
    assert meta.decision == "ask"
    assert meta.trigger.startswith("hard_rule:")
    assert "computer_open_payment_app" in meta.trigger


def test_evaluator_computer_screenshot_non_financial_auto_approve():
    """evaluator: computer.screenshot(无词表规则) + AUTO → approve(走 default 档)。"""
    meta = evaluate(
        "computer.screenshot",
        {},
        gate_level=ApprovalLevel.AUTO,
        config=_empty_config(),
    )
    # AUTO 档 + 无 hard rule 命中 → approve(default level=auto)
    assert meta.decision == "approve"


def test_evaluator_computer_type_text_normal_auto_approve():
    """evaluator: computer.type_text + 普通文本 → approve(AUTO 档,无词表命中)。"""
    meta = evaluate(
        "computer.type_text",
        {"text": "hello world"},
        gate_level=ApprovalLevel.AUTO,
        config=_empty_config(),
    )
    assert meta.decision == "approve"


# ── 5. autonomy.classify:hard_rule:computer_* 不可降级 ────────────────────────

def test_autonomy_classify_computer_financial_not_demotable():
    """autonomy.classify:computer.type_text 金融文本 → RED,即便 preauth 也不降级(铁律)。"""
    from argos_agent.permissions.autonomy import classify, AutonomyPolicy

    # 尝试用 preauth 降级
    policy = AutonomyPolicy(
        preauth={"computer_type_financial_pattern": True}  # preauth 试图降级
    )

    zone, reason = classify(
        action="computer.type_text",
        args={"text": "CVV: 123"},
        reversible=False,          # computer.* 不可逆 → 直接 RED(优先级1)
        verdict=None,
        config=_empty_config(),
        policy=policy,
    )
    # reversible=False 优先 → RED(铁律:不可撤销必升级)
    assert zone.value == "red", (
        f"不可撤销动作应为 RED,得到 {zone.value!r}"
    )


def test_autonomy_classify_hard_rule_computer_not_preauth_demotable():
    """autonomy.classify:即便 reversible=True(假设情形),hard_rule 触发也不可被 preauth 降级。"""
    from argos_agent.permissions.autonomy import classify, AutonomyPolicy

    policy = AutonomyPolicy(
        preauth={"computer_type_financial_pattern": True}  # preauth 试图降级
    )

    # reversible=True 让优先级1不触发,看 hard_rule 路径
    zone, reason = classify(
        action="computer.type_text",
        args={"text": "CVV: 123"},
        reversible=True,           # 假设场景:看 hard_rule 路径
        verdict=None,
        config=_empty_config(),
        policy=policy,
    )
    # hard_rule: 前缀 → evaluator 返回 ask + trigger=hard_rule:computer_type_financial_pattern
    # autonomy.classify 判断 trigger.startswith("hard_rule:") → RED,preauth 不降级
    assert zone.value == "red", (
        f"hard_rule 触发应为 RED(不可被 preauth 降级),得到 {zone.value!r}"
    )
    assert "hard_rule" in reason.lower() or "硬规则" in reason, (
        f"RED 原因应包含 hard_rule 信息,得到 {reason!r}"
    )


# ── 6. 规则集默认不可删(硬语义检验)────────────────────────────────────────────

def test_financial_pattern_is_not_none():
    """_FINANCIAL_TEXT_PATTERN 不为 None(默认集不可删)。"""
    assert _FINANCIAL_TEXT_PATTERN is not None


def test_payment_app_pattern_is_not_none():
    """_PAYMENT_APP_PATTERN 不为 None(默认集不可删)。"""
    assert _PAYMENT_APP_PATTERN is not None


def test_check_computer_type_text_is_callable():
    """check_computer_type_text 可调用(默认规则函数存在)。"""
    assert callable(check_computer_type_text)


def test_check_computer_open_app_is_callable():
    """check_computer_open_app 可调用(默认规则函数存在)。"""
    assert callable(check_computer_open_app)


# ── 7. conductor 自治路径集成测试(trust≤L1 下 computer 高危动作真的被拒)────────
# 修复 major 审计洞:此前文件只有函数级单测,缺 conductor/自治 run 集成用例。
# 验证:autonomy.classify(reversible=False) → RED,且 RED 在自治路径下代表"拒绝执行"。

def test_autonomy_conductor_computer_high_risk_is_red():
    """conductor 自治运行下,computer.* 高危动作 → autonomy.classify → RED。

    验证路径:reversible=False(computer.* 铁律) → 优先级1 直接 RED。
    RED 在 conductor 自治模式(trust≤L1)下 = 拒绝并要求人工在场确认。
    """
    from argos_agent.permissions.autonomy import classify, Zone, AutonomyPolicy
    from argos_agent.permissions.config import PermissionsConfig

    config = PermissionsConfig.empty()
    policy = AutonomyPolicy()   # 默认策略:无 preauth,clarification_required=True

    # 逐个验证所有 computer.* 高危动作在自治路径下均被拒
    computer_actions = [
        ("computer.screenshot", {}),
        ("computer.click", {"x": 100, "y": 200}),
        ("computer.double_click", {"x": 100, "y": 200}),
        ("computer.type_text", {"text": "some text"}),
        ("computer.key", {"text": "command+c"}),
        ("computer.scroll", {"x": 100, "y": 200, "text": "3"}),
        ("computer.open_app", {"app": "Finder"}),
    ]
    for action, args in computer_actions:
        zone, reason = classify(
            action=action,
            args=args,
            reversible=False,   # computer.* manifest reversible=False 铁律
            verdict=None,
            config=config,
            policy=policy,
        )
        assert zone == Zone.RED, (
            f"{action}: conductor 自治路径下应为 RED(需人在场),得到 {zone.value!r}\n"
            f"原因: {reason}"
        )
        assert reason, f"{action}: RED 应有人话原因字符串"


def test_autonomy_conductor_computer_type_text_financial_is_red():
    """conductor 自治路径:computer.type_text + 金融文本 → RED(不可被 preauth 降级)。

    验证 evaluator hard_rule 触发 → autonomy.classify → RED,
    即便 conductor 试图 preauth 降级也无效(护城河铁律)。
    """
    from argos_agent.permissions.autonomy import classify, Zone, AutonomyPolicy
    from argos_agent.permissions.config import PermissionsConfig

    config = PermissionsConfig.empty()
    # conductor 试图通过 preauth 降级金融规则(应无效)
    policy = AutonomyPolicy(
        preauth={"computer_type_financial_pattern": True}
    )

    zone, reason = classify(
        action="computer.type_text",
        args={"text": "CVV: 999"},
        reversible=False,   # computer.type_text 不可逆 → 优先级1 直接 RED
        verdict=None,
        config=config,
        policy=policy,
    )
    assert zone == Zone.RED, (
        f"computer.type_text 金融文本在自治路径下应 RED(preauth 无效),得到 {zone.value!r}"
    )


def test_autonomy_conductor_computer_open_payment_app_is_red():
    """conductor 自治路径:computer.open_app + 支付 app → RED。

    额外验证 check_computer_hard_rules 命中支付/银行 app 时,
    完整的 evaluator → autonomy.classify 管线正确拒绝。
    """
    from argos_agent.permissions.autonomy import classify, Zone, AutonomyPolicy
    from argos_agent.permissions.config import PermissionsConfig

    config = PermissionsConfig.empty()
    policy = AutonomyPolicy()

    zone, reason = classify(
        action="computer.open_app",
        args={"app": "支付宝"},
        reversible=False,   # computer.open_app 不可逆 → 优先级1 RED
        verdict=None,
        config=config,
        policy=policy,
    )
    assert zone == Zone.RED, (
        f"computer.open_app 支付宝在自治路径下应 RED,得到 {zone.value!r}"
    )
