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
from pathlib import Path
from typing import Any

from argos_agent.approval import ApprovalGate, ApprovalLevel
from argos_agent.tools import shell as _shell
from argos_agent.tools import web as _web
from argos_agent.tools.receipts import Receipt, ReceiptSigner
from .egress import EgressPolicy

# 网络类动作:request 前要查 egress。
_NETWORK_ACTIONS: set[str] = {"web_search", "web_extract"}
# 各 action 的风险与人类描述模板(审批弹窗用)。
# C1:run_command 提到 high —— 任意 shell 执行,即便已关进 Seatbelt 也绝不静默放手。
_RISK: dict[str, str] = {
    "run_command": "high",
    "web_search": "low",
    "web_extract": "low",
    # 计算机控制(浏览器):读类(导航/快照/截图)low;写类(点击/填表 = 可触发表单提交)medium。
    "browser_navigate": "low",
    "browser_snapshot": "low",
    "browser_screenshot": "low",
    "browser_click": "medium",
    "browser_type": "medium",
    # MCP 外部工具调用:第三方 server 能力不可预知 → medium,默认走审批。
    "mcp_call": "medium",
}
# C1:这些 action 即便在 AUTO(YOLO)档也强制逐个确认 —— 永不静默执行 shell。
_FORCE_CONFIRM_ACTIONS: set[str] = {"run_command"}


@dataclass(frozen=True, slots=True)
class BrokerResult:
    value: Any
    receipt: Receipt


class CapabilityBroker:
    def __init__(self, *, gate: ApprovalGate, egress: EgressPolicy,
                 signer: ReceiptSigner, workspace: Path | None = None) -> None:
        self._gate = gate
        self._egress = egress
        self._signer = signer
        # host 侧 run_command 的工作目录 —— 必须与沙箱子进程(write_file 落地处)同一个 ws,
        # 否则 --project 模式下 run_command 跑在默认 ~/.argos/workspace、write_file 落在项目目录
        # → 脚本读不到刚写的文件(workspace 分叉 bug)。None 时回退 shell 自己的 _ws() 解析。
        self._workspace = workspace
        self.last_receipt: Receipt | None = None   # loop 读它投 ToolReceipt 事件

    async def request(self, action: str, args: dict[str, Any]) -> Any:
        """返回灌回沙箱的值(成功=工具串;拒绝=拒绝串)。副作用:签 Receipt 存 last_receipt。

        唯一 gating 入口:egress → approval → host 执行 → 签 Receipt。沙箱侧只能经
        executor 的 broker RPC 走到这里。_execute() 是内部裸执行,绝不可绕开本方法直接调
        (那会跳过 egress/approval/receipt;见 _execute docstring)。"""
        if action not in _RISK:
            return f"错误:未知/不支持的特权动作 {action!r},拒绝。"
        # ① egress 检查(网络类,fail-closed)
        if action in _NETWORK_ACTIONS:
            host = _web.host_for(action, args)
            # web_extract:校验目标 url 的 host;web_search:校验活跃 provider 的出口 host(I3)。
            # 两者都 fail-closed —— host 不在白名单即拒,绝不静默放行。
            if not self._egress.allowed(host):
                return f"错误:egress 拒绝 —— {host!r} 不在允许出网名单。可让用户批准该域名后重试。"
        # ② 审批拨盘
        # C1:run_command 即便在 AUTO 档也强制逐个确认 —— 永不静默执行任意 shell。
        level_override = (
            ApprovalLevel.CONFIRM
            if (action in _FORCE_CONFIRM_ACTIONS and self._gate.level is ApprovalLevel.AUTO)
            else None
        )
        decision = await self._request_decision(action, args, level_override)
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

    async def _request_decision(self, action: str, args: dict[str, Any],
                                level_override: "ApprovalLevel | None"):
        """走审批拨盘。level_override 非 None 时临时降级(如 run_command 在 AUTO 档强制 CONFIRM),
        裁决后恢复原档(避免污染整个 session)。"""
        if level_override is None:
            return await self._gate.request(
                action, args, description=self._describe(action, args),
                risk=_RISK.get(action, "medium"),
            )
        saved = self._gate.level
        self._gate.set_level(level_override)
        try:
            return await self._gate.request(
                action, args, description=self._describe(action, args),
                risk=_RISK.get(action, "medium"),
            )
        finally:
            self._gate.set_level(saved)

    @property
    def signer(self) -> ReceiptSigner:
        """host 侧暴露签名器 —— 供 Harness.accept_receipt 在投 ToolReceipt 前核验回执
        (W2/§6.5)。broker 与 Harness/loop 同在 host 进程,沙箱拿到的只是 RPC stub,
        故此暴露不泄露 key 给沙箱。"""
        return self._signer

    def take_receipt(self) -> Receipt | None:
        """I2:返回并清空 last_receipt —— loop 每步调它,确保只在【本步新签了 Receipt】时
        才投 ToolReceipt 事件;无新回执返回 None(防陈旧回执被反复重投/张冠李戴)。"""
        rec = self.last_receipt
        self.last_receipt = None
        return rec

    def _execute(self, action: str, args: dict[str, Any]) -> tuple[Any, int | None]:
        """⚠️ 内部裸执行 —— 仅供 request() 调用。绝不可从外部/测试直接调:
        它跳过 egress 校验、审批裁决与 Receipt 签发,直接产生真副作用。
        所有 broker-gated 动作必须经 request() 入口(它做完整 gating)。"""
        if action == "run_command":
            return _shell.run_command(args.get("command", ""), workspace=self._workspace)
        if action == "web_search":
            return _web.web_search(args.get("query", ""), int(args.get("limit", 5))), None
        if action == "web_extract":
            return _web.web_extract(args.get("url", "")), None
        # 计算机控制(浏览器):走进程内单例 BrowserController(独占线程跑 sync Playwright,
        # 绕开 asyncio loop 线程冲突);懒启动、无 chromium 时返回诚实错误串。
        if action.startswith("browser_"):
            from argos_agent import browser as _browser
            ctrl = _browser.get_controller()
            if action == "browser_navigate":
                return ctrl.navigate(args.get("url", "")), None
            if action == "browser_snapshot":
                return ctrl.snapshot(int(args.get("max_chars", 4000))), None
            if action == "browser_click":
                return ctrl.click(args.get("selector", "")), None
            if action == "browser_type":
                return ctrl.type_text(args.get("selector", ""), args.get("text", "")), None
            if action == "browser_screenshot":
                return ctrl.screenshot(args.get("path", "screenshot.png")), None
        # MCP 外部工具:转给进程内 McpManager(懒连 ~/.argos/mcp.json 的 stdio server)。
        if action == "mcp_call":
            from argos_agent import mcp_native
            mgr = mcp_native.get_manager()
            arguments = args.get("arguments")
            if not isinstance(arguments, dict):
                arguments = {}
            return mgr.call(args.get("server", ""), args.get("tool", ""), arguments), None
        # 未知 action 已被 request 顶部挡掉;此处兜底诚实返回。
        return f"错误:动作 {action!r} 暂未实现 host 执行。", None

    @staticmethod
    def _describe(action: str, args: dict[str, Any]) -> str:
        if action == "run_command":
            return f"执行命令 {args.get('command', '')}"
        if action == "web_search":
            return f"联网搜索 {args.get('query', '')}"
        if action == "web_extract":
            return f"取网页 {args.get('url', '')}"
        if action == "browser_navigate":
            return f"浏览器打开 {args.get('url', '')}"
        if action == "browser_snapshot":
            return "读取当前浏览器页面内容"
        if action == "browser_screenshot":
            return f"浏览器截图到 {args.get('path', 'screenshot.png')}"
        if action == "browser_click":
            return f"浏览器点击 {args.get('selector', '')}"
        if action == "browser_type":
            return f"浏览器在 {args.get('selector', '')} 填入文本"
        if action == "mcp_call":
            return f"调用 MCP 工具 {args.get('server', '')}/{args.get('tool', '')}"
        return f"{action} {args}"
