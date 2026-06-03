"""CapabilityBroker —— host 侧特权动作边界(契约 §5 + spec §6.2/§6.5/§6.6).

沙箱内 broker-gated 工具发 broker_call;host 侧本类:
  ① egress 检查(网络类动作查 allowlist);
  ② 审批拨盘裁决(ApprovalGate.request,按 ApprovalLevel);
  ③ 批准 → 在 host 执行真副作用(shell/web 真实现);
  ④ 签 Receipt(HMAC)→ 暴露 last_receipt(loop 据此投 ToolReceipt 事件 + 存 events);
  ⑤ 返回结果灌回沙箱。
拒绝/超时 → fail-closed 返回拒绝串(模型看到换路,不抛异常;沿用 approval.guarded_call 语义)。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from argos_agent.approval import ApprovalGate
from argos_agent.tools import shell as _shell
from argos_agent.tools import web as _web
from argos_agent.tools.receipts import Receipt, ReceiptSigner
from .egress import EgressPolicy

# 网络类动作:request 前要查 egress。
_NETWORK_ACTIONS: set[str] = {"web_search", "web_extract"}
# 各 action 的风险与人类描述模板(审批弹窗用)。
_RISK: dict[str, str] = {
    "run_command": "medium",
    "web_search": "low",
    "web_extract": "low",
    "navigate": "low",
    "click": "low",
    "type_text": "medium",
}


@dataclass(frozen=True, slots=True)
class BrokerResult:
    value: Any
    receipt: Receipt


class CapabilityBroker:
    def __init__(self, *, gate: ApprovalGate, egress: EgressPolicy,
                 signer: ReceiptSigner) -> None:
        self._gate = gate
        self._egress = egress
        self._signer = signer
        self.last_receipt: Receipt | None = None   # loop 读它投 ToolReceipt 事件

    async def request(self, action: str, args: dict[str, Any]) -> Any:
        """返回灌回沙箱的值(成功=工具串;拒绝=拒绝串)。副作用:签 Receipt 存 last_receipt。"""
        if action not in _RISK:
            return f"错误:未知/不支持的特权动作 {action!r},拒绝。"
        # ① egress 检查(网络类)
        if action in _NETWORK_ACTIONS:
            host = _web.host_for(action, args)
            # web_search 出口由 provider 决定,只要 search_hosts 非空即视为允许 provider;
            # web_extract 必须显式校验目标 url 的 host。
            if action == "web_extract" and not self._egress.allowed(host):
                return f"错误:egress 拒绝 —— {host!r} 不在允许出网名单。可让用户批准该域名后重试。"
        # ② 审批拨盘
        decision = await self._gate.request(
            action, args, description=self._describe(action, args),
            risk=_RISK.get(action, "medium"),
        )
        if not decision.approved:
            return (
                f"用户拒绝执行该操作({decision.reason or '未提供原因'})。"
                f"请尝试其他做法或向用户解释为什么需要它。"
            )
        # ③ host 执行真副作用
        value, exit_code = self._execute(action, args)
        # ④ 签 Receipt(HMAC,host 侧)
        self.last_receipt = self._signer.sign(
            action=action, args=args, result=value, exit_code=exit_code,
        )
        # ⑤ 灌回沙箱
        return value

    def _execute(self, action: str, args: dict[str, Any]) -> tuple[Any, int | None]:
        if action == "run_command":
            return _shell.run_command(args.get("command", ""))
        if action == "web_search":
            return _web.web_search(args.get("query", ""), int(args.get("limit", 5))), None
        if action == "web_extract":
            return _web.web_extract(args.get("url", "")), None
        # playwright 等(可选)在 Phase 5/6 接;此处未知 action 已被 request 顶部挡掉。
        return f"错误:动作 {action!r} 暂未实现 host 执行。", None

    @staticmethod
    def _describe(action: str, args: dict[str, Any]) -> str:
        if action == "run_command":
            return f"执行命令 {args.get('command', '')}"
        if action == "web_search":
            return f"联网搜索 {args.get('query', '')}"
        if action == "web_extract":
            return f"取网页 {args.get('url', '')}"
        return f"{action} {args}"
