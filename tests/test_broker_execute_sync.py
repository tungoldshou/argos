"""#3 治理地基:同步桥路径(execute_sync)补回 egress + Receipt + fail-closed。

bug:app_factory / subagent / __main__ / setup_wizard 的同步桥(exec_code 阻塞无法 await gate)
直调 broker._execute,旁路 request() 的 egress 校验 / 审批 / Receipt 签发 / 审计 → 「每个动作
签名回执」「可审计」这两个产品承诺在沙箱工具路径结构性落空(ledger 对真实工具调用基本为空)。
修法:execute_sync 做 request() 的所有【同步】步骤(fail-closed + egress + 执行 + 签回执),
唯独跳过②交互审批(需 await,留 v1.1;真边界仍是 Seatbelt OS 沙箱)。
"""
from __future__ import annotations

import pytest

from argos.approval import ApprovalGate, ApprovalLevel
from argos.sandbox.broker import CapabilityBroker
from argos.sandbox.egress import EgressPolicy
from argos.tools.receipts import ReceiptSigner


def _broker(workspace=None):
    gate = ApprovalGate(level=ApprovalLevel.AUTO)
    egress = EgressPolicy(llm_hosts={"api.minimaxi.com"},
                          search_hosts={"duckduckgo.com"}, mcp_hosts=set())
    signer = ReceiptSigner(key=b"host-only-key")
    return CapabilityBroker(gate=gate, egress=egress, signer=signer, workspace=workspace)


def test_execute_sync_blocks_financial_computer_hard_rule():
    """#11 排查修复:计算机控制的金融/验证码硬规则声明"任何档位均不可降级"的人在场确认,
    过去只在 request() 异步审批路径生效。同步桥(workflow 子 agent AUTO)直落 _execute → 被绕过。
    现 execute_sync 对 computer_* 命中硬规则时 fail-closed 拒(无法交互审批),且不签回执、不真执行。"""
    br = _broker()
    # 开支付/银行 app → 拒(拒绝串 + 不签回执 == 没到 _execute)
    val, code = br.execute_sync("computer_open_app", {"app": "支付宝"})
    assert code == 1 and "硬规则" in val and "fail-closed" in val, val
    assert br.take_receipt() is None, "被硬规则拒不签回执(证明未真执行)"
    # 键入卡号(16 位)→ 拒
    val2, code2 = br.execute_sync("computer_type_text", {"text": "4111 1111 1111 1111"})
    assert code2 == 1 and "硬规则" in val2, val2
    assert br.take_receipt() is None


def test_execute_sync_allows_benign_computer_action(monkeypatch):
    """非金融 computer_* 动作(如开普通 app)不被该硬规则拦 —— 仅金融/验证码场景 fail-closed。
    monkeypatch _execute 隔离真 ComputerExecutor(CI 无显示/辅助权限)。"""
    br = _broker()
    monkeypatch.setattr(br, "_execute", lambda action, args, run_ctx=None, _gated=False: ("opened", 0))
    val, code = br.execute_sync("computer_open_app", {"app": "Calculator"})
    assert "硬规则" not in str(val) and val == "opened", val   # 未命中金融规则 → 放行到 _execute


def test_execute_sync_signs_receipt(monkeypatch):
    """同步桥执行后必须签发 Receipt(治理铁证),loop take_receipt → ToolReceipt → ledger 落盘。
    过去裸 _execute 不签 → ledger 对沙箱工具基本为空。"""
    def fake_run(command, *, workspace=None):
        return ("ok", 0)
    monkeypatch.setattr("argos.tools.shell.run_command", fake_run)
    br = _broker()
    value, exit_code = br.execute_sync("run_command", {"command": "ls"})
    assert value == "ok"
    rec = br.take_receipt()
    assert rec is not None and rec.action == "run_command"   # 回执真实签发


def test_execute_sync_enforces_egress():
    """同步桥路径也走出网 fail-closed —— 绝不裸执行旁路(防 SSRF/外泄,6448 治理修复)。
    web_extract 到云元数据端点 → SSRF 硬挡(2026-06-18 起 web_extract 放行公网、只拒内网,
    故文案是 SSRF 而非白名单;关键不变量不变:内网端点经同步桥仍被拒、不签回执)。"""
    br = _broker()
    value, exit_code = br.execute_sync(
        "web_extract", {"url": "http://169.254.169.254/latest/meta-data/"}
    )
    assert "SSRF" in str(value) or "内网" in str(value) or "egress 拒绝" in str(value)  # 内网元数据端点被拒
    assert br.take_receipt() is None     # 被拒不签回执(无副作用)


def test_execute_sync_rejects_unknown_action():
    """fail-closed:未知/不支持的特权动作经同步桥也拒,不裸执行。"""
    br = _broker()
    value, _ = br.execute_sync("frobnicate", {})
    assert "未知" in str(value) or "拒绝" in str(value)
    assert br.take_receipt() is None
