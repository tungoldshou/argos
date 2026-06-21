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

import asyncio
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from argos.approval import ApprovalGate
from argos.tools import files as _files
from argos.tools import shell as _shell
from argos.tools import web as _web
from argos.tools.receipts import Receipt, ReceiptSigner
from .egress import EgressPolicy

if TYPE_CHECKING:
    from argos.capability.registry import CapabilityRegistry

# 网络类动作:request 前要查 egress。
_NETWORK_ACTIONS: set[str] = {"web_search", "web_extract"}


def _resolve_lsp_server(
    *,
    file: "str | None",
    manager: "Any",
) -> "str | None":
    """根据文件扩展名从 LspManager 配置中解析对应 server 名。

    原 bug:broker._execute 的 LSP 分支全部硬编 server_name="python",导致
    任何非 Python 语言服务器配置了也永远路由不到。

    修复策略:
      - file 非 None:取扩展名,查 LspConfig.get_servers_for_filetype(ext),
        返回第一个未 disabled 的 server name。
      - file is None(如 lsp_workspace_symbols 无目标文件):返回配置的第一个
        未 disabled server。
      - 无匹配 server → 返回 None(调用方返 clear error JSON,不静默路由到错误 server)。

    参数:
      file    — 目标文件路径字符串(可含路径前缀);或 None。
      manager — LspManager 实例(需有 .config 属性 LspConfig)。

    返回:
      str  — 第一个匹配 server 的名字。
      None — 无匹配或无配置。
    """
    try:
        cfg = manager.config
    except AttributeError:
        return None

    if file is not None:
        ext = Path(file).suffix  # e.g. ".py", ".rs", ""
        if ext:
            matches = cfg.get_servers_for_filetype(ext)
            if matches:
                return matches[0][0]
        return None
    else:
        # 无文件:返回第一个未 disabled 的 server
        for name, sc in cfg.servers.items():
            if not sc.disabled:
                return name
        return None
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
    # OS 级计算机控制:屏幕/鼠标是全局资源,Seatbelt 关不住 → 全部 high。
    # 静态兜底:即便 registry=None(headless/旧测试路径),computer.* 仍受高风险管辖。
    "computer_screenshot": "high",
    "computer_click": "high",
    "computer_double_click": "high",
    "computer_type_text": "high",
    "computer_key": "high",
    "computer_scroll": "high",
    "computer_open_app": "high",
    # 文件写:gate-only(host 跑 hard-path/密钥 + 签回执;落盘在 Seatbelt 子进程)。registry
    # 已声明它们,这里给无 registry 的 fallback 路径(headless/旧测试)也认得 → fail-closed 不误拒。
    # risk 与 builtins 注册值一致(medium),否则 test_builtin_risk_table_matches_broker_RISK 失败。
    "write_file": "medium",
    "edit_file": "medium",
}
# 文件写:broker 只做 host 侧 gate-only 治理(hard-path/密钥/回执),真正落盘留在 Seatbelt 子进程。
# (历史上有过 _FORCE_CONFIRM_ACTIONS:即便 AUTO 也逐条确认的清单。2026-06-20 用户反馈"太鸡肋"后
#  清空,Phase 4 删除整套机制 —— YOLO 兑现全自治,危险命令仍由 evaluator 的 check_hard_shell 硬拦。)
_FILE_WRITE_ACTIONS: set[str] = {"write_file", "edit_file"}


@dataclass(frozen=True, slots=True)
class BrokerResult:
    value: Any
    receipt: Receipt


class CapabilityBroker:
    def __init__(self, *, gate: ApprovalGate, egress: EgressPolicy,
                 signer: ReceiptSigner, workspace: Path | None = None,
                 mcp_manager: Any = None, browser_controller: Any = None,
                 registry: "CapabilityRegistry | None" = None) -> None:
        self._gate = gate
        self._egress = egress
        self._signer = signer
        # host 侧 run_command 的工作目录 —— 必须与沙箱子进程(write_file 落地处)同一个 ws,
        # 否则 --project 模式下 run_command 跑在默认 ~/.argos/workspace、write_file 落在项目目录
        # → 脚本读不到刚写的文件(workspace 分叉 bug)。None 时回退 shell 自己的 _ws() 解析。
        self._workspace = workspace
        self.last_receipt: Receipt | None = None   # loop 读它投 ToolReceipt 事件
        # per-session MCP/browser 实例(从 AppComponents 注入);None = fallback 到模块级单例
        # (向后兼容测试/headless 路径)。
        self._mcp_manager = mcp_manager
        self._browser_controller = browser_controller
        # P2 能力注册表(可选):None = 兼容旧路径,行为完全不变。
        # 非 None 时:risk 查表优先走 registry.risk_table(),内置 _RISK 作 fallback 兜底;
        # _execute 前先尝试 registry dispatch;LSP 等仅注册表知晓的能力方可通过 request()。
        self._registry = registry
        # 同步桥交互审批:run 起点由 AgentLoop 注入 host event loop;broker_handler 在
        # exec_code 工作线程里据此把 request() 提交回主循环(主循环此刻空闲 → 交互审批能 await)。
        # None = 无 host loop(headless/旧测试)→ request_blocking 回退 execute_sync。
        self._host_loop: Any = None
        # 桥阻塞上限:gate.request 自身 60s 超时,300s 是安全上界(防主循环异常死等)。
        self._bridge_timeout: float = 300.0
        # 计算机控制截图工件(path, size):computer_screenshot 执行后 stash;loop 取它把
        # 截图当图像挂到下一条反馈消息回给模型(视觉回路)。None = 本步无新截图。
        self.last_computer_artifact: tuple[str, tuple | None] | None = None

    def _egress_deny_reason(self, action: str, args: dict[str, Any]) -> str | None:
        """网络类动作的出网裁决(fail-closed)。允许 → None;拒绝 → 人类可读原因(不含"错误:"前缀)。
        request() 与同步桥 execute_sync() 共用,保证两条路径裁决一致(6323 SSRF 修复要求)。

        · web_extract:目标 URL 由 agent 动态选(能力清单声明 egress_hosts=("*"))→ 放行任意
          【公网】host,只硬挡私网/回环/保留/云元数据(SSRF)。出网控制不靠静态白名单,而靠
          SSRF 双层防护(此处 + _http_get 内逐跳)+ 审批拨盘 + 每次签 HMAC 回执(全程留痕)。
        · 其余网络动作(web_search 等):维持固定 provider 白名单 fail-closed —— host 不在白名单即拒。"""
        host = _web.host_for(action, args)
        if action == "web_extract":
            if _web.extract_url_blocked(args.get("url", "")):
                return f"SSRF 防护拒绝私网/保留/内网地址(web_extract 仅允许公网 URL):{host!r}"
            return None
        if not self._egress.allowed(host):
            return f"egress 拒绝 —— {host!r} 不在允许出网名单。可让用户批准该域名后重试。"
        return None

    def _preflight(self, action: str, args: dict[str, Any]
                   ) -> "tuple[tuple[Any, int | None] | None, dict[str, str]]":
        """两条 gating 路径(request / execute_sync)共享的【同步前置】—— 单一真源,杜绝分叉漏检:
          ① fail-closed:action 必须在 registry 或内置 _RISK 之一(LSP 等仅在 registry 的动作也放行)。
          ② 文件写 gate-only:host 裁决 hard-path/密钥 + 签回执,落盘留 Seatbelt 子进程。
          ③ egress 检查:网络类动作查 allowlist/SSRF(manifest 驱动)。

        返回 (terminal, registry_risk):
          · terminal=(value, exit_code) → 前置已得最终结果,调用方直接返回(不再继续执行)。
          · terminal=None → 放行,调用方继续各自后续(request:交互审批 + 出网阀执行;
            execute_sync:computer 硬规则 fail-closed + 执行)。
        registry_risk 透传给 request 的审批步(risk 表快照)。"""
        # getattr 防御：object.__new__ 绕过 __init__ 的旧测试路径没有 _registry 属性
        _reg = getattr(self, "_registry", None)
        registry_risk = _reg.risk_table() if _reg is not None else {}
        if action not in registry_risk and action not in _RISK:
            return (f"错误:未知/不支持的特权动作 {action!r},拒绝。", 1), registry_risk
        # ①a run_command 危险命令 hard rule(2026-06-20 review #1):两条路都拦。
        # 此前 check_hard_shell 只在 request() 的异步审批路径(evaluator)里跑;execute_sync(workflow
        # 子 agent / 无 host_loop 回退)直落 _execute → rm -rf/curl|sh/git -c <hook> 等在 sync 桥旁路。
        # 且非 darwin run_command 裸跑(无 Seatbelt)。放进 _preflight 让所有路径 fail-closed 一致拦死,
        # 兑现 broker/shell docstring "危险命令仍被 check_hard_shell 兜底拦" 的承诺。
        if action == "run_command":
            from argos.permissions.hard_rules import check_hard_shell
            _rule = check_hard_shell(str(args.get("command", "")))
            if _rule is not None:
                return (f"错误:命令命中危险硬规则({_rule}),拒绝执行。", 1), registry_risk
        if action in _FILE_WRITE_ACTIONS:
            val = self._gate_only_write(action, args)
            return (val, (0 if val == _files.WRITE_APPROVED_SENTINEL else 1)), registry_risk
        if action in self._derive_network_actions():
            deny = self._egress_deny_reason(action, args)
            if deny is not None:
                return (f"错误:{deny}", 1), registry_risk
        return None, registry_risk

    async def request(self, action: str, args: dict[str, Any]) -> Any:
        """返回灌回沙箱的值(成功=工具串;拒绝=拒绝串)。副作用:签 Receipt 存 last_receipt。

        唯一 gating 入口:_preflight(action 合法性/文件写/egress)→ approval → host 执行 → 签 Receipt。
        沙箱侧只能经 executor 的 broker RPC 走到这里。_execute() 是内部裸执行,绝不可绕开本方法直接调
        (那会跳过 egress/approval/receipt;见 _execute docstring)。
        """
        # ── ①②③ 共享前置(与 execute_sync 同源)── terminal 命中即返(只取 value,exit_code 给同步桥用)。
        terminal, _registry_risk = self._preflight(action, args)
        if terminal is not None:
            return terminal[0]
        # ② 审批拨盘(L4/YOLO 不再把任何动作从 AUTO 强制升 CONFIRM —— 全自治,HARD RULES 仍拦)。
        decision = await self._request_decision(action, args, registry_risk=_registry_risk)
        if not decision.approved:
            return (
                f"用户拒绝执行该操作({decision.reason or '未提供原因'})。"
                f"请尝试其他做法或向用户解释为什么需要它。"
            )
        # ③ host 执行真副作用
        # 出网阀(2026-06-20):run_command 走到这步 = 已批准。命令若需联网(pip install / git push /
        # curl …),用 allow_network=True 的 Seatbelt profile 跑(临时开网);否则牢笼网络默认 OFF。
        # Cautious 下联网命令不被"牢笼内自动放行"短路(evaluator 已排除)→ 这里的批准是用户真点的;
        # Autonomous 下 evaluator 直接 approve → 自动开网(Codex YOLO);写牢笼+凭据读拒始终在。
        _allow_net = (action == "run_command"
                      and _shell.command_needs_network(args.get("command", "")))
        # egress 精确加白(P1 Fix 2 — 2026-06-21):
        # 出网阀批准后,把从命令中能解析到的目标 host 加进 egress allowlist(精确加白)。
        # 这让"批准 curl a.com"只使 a.com 进白名单,evil.com 仍被拒。
        # 对 host 不可解析的命令(pip/npm/git push),不做盲猜 —— host 未知留 TODO。
        # TODO(future): for pip/npm/git, enumerate known registry hosts and add them here
        #   instead of blanket-opening the OS network without egress audit trail.
        if _allow_net:
            _parsed_host = _shell.parse_network_host(args.get("command", ""))
            if _parsed_host:
                self._egress.allow(_parsed_host)
        value, exit_code = self._execute(action, args, run_ctx=None, _gated=True,
                                         allow_network=_allow_net)
        # ④ 签 Receipt(HMAC,host 侧)
        self.last_receipt = self._signer.sign(
            action=action, args=args, result=value, exit_code=exit_code,
        )
        # ⑤ 灌回沙箱
        return value

    def execute_sync(self, action: str, args: dict[str, Any]) -> tuple[Any, int | None]:
        """同步 gating 路径(供同步桥 broker_handler:exec_code 阻塞等结果,无法 await gate)。

        做 request() 的所有【同步】步骤——fail-closed action 校验 + ① egress 检查 + ③ 真执行 +
        ④ Receipt 签发——唯独跳过 ② 交互审批(需 await,留 v1.1;真边界仍是 Seatbelt OS 沙箱)。

        修复 #3 治理地基:同步桥过去直调 _execute 旁路 egress / 回执 / 审计 → 「每个动作签名回执」
        「可审计」承诺在沙箱工具路径结构性落空(ledger 基本为空)。execute_sync 让回执真实签发
        (loop take_receipt → ToolReceipt → ledger 落盘),egress 第二防线在同步桥路径生效。

        _gated 保持默认 False:registry dispatch 能力仍走 _execute 的 PermissionError(它们需经
        request() 的审批,同步桥给不了),不在此放行;内置 if/elif 工具(run_command/web_*/...)
        正常执行并补 egress + 回执。
        """
        # ── ①②③ 共享前置(与 request() 同源 _preflight:action 合法性 + 文件写 gate-only + egress)──
        terminal, _registry_risk = self._preflight(action, args)
        if terminal is not None:
            return terminal
        # ①b 计算机控制金融/验证码硬规则:声明"任何档位均不可降级"的人在场确认,过去只在 request()
        # 的异步审批路径(_request_decision→gate→evaluator)生效。同步桥(workflow 子 agent 走 AUTO、
        # 不注入 host_loop)直落 _execute → 该硬规则被悄悄绕过(2026-06-18 排查 #11)。同步桥无法交互审批,
        # 故 fail-closed 拒,而不是静默执行支付/银行 app 或键入卡号/OTP。镜像 _gate_only_write 的 host 侧裁决。
        if action.startswith("computer_"):
            from argos.permissions.hard_rules import check_computer_hard_rules
            _rule = check_computer_hard_rules(action, args)
            if _rule:
                return (
                    f"错误:计算机控制命中非开发者域硬规则({_rule}),需人在场确认;"
                    "同步桥(子 agent AUTO)无法交互审批 → fail-closed 拒绝。", 1
                )
        # ③ host 执行真副作用(② 交互审批跳过 —— 同步桥无法 await)
        value, exit_code = self._execute(action, args, run_ctx=None)
        # ④ 签 Receipt(HMAC,host 侧):沙箱工具调用现在真有签名回执 + 可审计
        self.last_receipt = self._signer.sign(
            action=action, args=args, result=value, exit_code=exit_code,
        )
        return value, exit_code

    def set_host_loop(self, loop: Any) -> None:
        """注入/清空 run 的 host event loop(同步桥交互审批用)。AgentLoop 在 run 起点设、
        finally 清。None = request_blocking 回退 execute_sync(无交互审批,保兼容)。"""
        self._host_loop = loop

    def request_blocking(self, action: str, args: dict[str, Any]) -> Any:
        """同步桥入口(broker_handler 在 exec_code 工作线程里调用):把 request() 提交回
        host_loop 阻塞等结果 —— 完整 gating(egress + 交互审批 + 执行 + 回执)。

        - host_loop 已设 → run_coroutine_threadsafe(request) + 阻塞等。exec_code 已被
          AgentLoop 移进工作线程,主循环此刻空闲 → gate.request 能 await 用户、TUI 能渲染审批卡。
        - host_loop 未设(headless/旧测试)→ 回退 execute_sync(egress + 执行 + 回执,跳过②交互
          审批)。行为同改造前,零回归。
        - 桥异常/超时 → fail-closed 返回拒绝串(模型看到换路,不抛;绝不静默放行)。
        """
        loop = self._host_loop
        if loop is None:
            value, _exit = self.execute_sync(action, args)
            return value
        try:
            fut = asyncio.run_coroutine_threadsafe(self.request(action, args), loop)
            return fut.result(timeout=self._bridge_timeout)
        except Exception as exc:  # noqa: BLE001 — 桥异常 fail-closed 拒
            return f"错误:审批桥异常({type(exc).__name__}),默认拒绝。"

    def _derive_network_actions(self) -> set[str]:
        """P2 egress manifest 驱动:从 registry 派生需要 egress 检查的动作集合。

        派生规则(spec §5 / 任务验收):
          cap.egress_hosts 非空(含 "*")的能力名集合 ∪ 原 _NETWORK_ACTIONS 兜底集合。
          无 registry 时 fallback = 原 _NETWORK_ACTIONS(行为零变更)。

        设计保证:
          · 内置 web_search / web_extract 在 builtins 里声明了 egress_hosts → 派生集合
            包含它们(与原集合等价,硬回归测试验证)。
          · 新注册能力只要在 manifest 里声明 egress_hosts 就自动进 egress 检查,无需改四处。
          · registry=None 时返回 _NETWORK_ACTIONS(向后兼容;零破坏测试)。
        """
        _reg = getattr(self, "_registry", None)
        if _reg is None:
            return set(_NETWORK_ACTIONS)
        try:
            # 从 registry 收集所有声明了 egress_hosts 的能力名(含 "*" 通配)。
            registry_egress: set[str] = set()
            for name in _reg.names():
                cap = _reg.get(name)
                if cap.egress_hosts:  # 非空 tuple = 有出网声明
                    registry_egress.add(name)
            # ∪ 原硬编码集合(兜底:确保 registry 不完整时核心网络动作仍受 egress 管辖)。
            return registry_egress | _NETWORK_ACTIONS
        except Exception:  # noqa: BLE001 — registry 访问失败 fallback 原集合(fail-safe)
            return set(_NETWORK_ACTIONS)

    async def _request_decision(self, action: str, args: dict[str, Any],
                                registry_risk: "dict[str, str] | None" = None):
        """走审批拨盘(gate.request)。

        registry_risk:registry.risk_table() 快照(P2);None 或缺失时退回内置 _RISK。
        优先级:registry_risk[action] > _RISK[action] > "medium" 默认。
        """
        _merged = {**_RISK, **(registry_risk or {})}
        risk_val = _merged.get(action, "medium")
        return await self._gate.request(
            action, args, description=self._describe(action, args),
            risk=risk_val,
        )

    @property
    def gate(self) -> ApprovalGate:
        """host 侧暴露审批闸 —— loop._run_workflow 在异步态(非 exec_code 内)await gate.request,
        TUI 据 WorkflowProposed.call_id 调 gate.respond 放行/拒绝。同 signer:沙箱拿不到。"""
        return self._gate

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

    def take_computer_artifact(self) -> "tuple[str, tuple | None] | None":
        """返回并清空 last_computer_artifact —— loop 每步调它,只在【本步新拍了截图】时拿到
        (path, size),据此把截图当图像挂到下一条反馈消息(视觉回路);无新截图返回 None。"""
        art = self.last_computer_artifact
        self.last_computer_artifact = None
        return art

    def _gate_only_write(self, action: str, args: dict[str, Any]) -> Any:
        """文件写 gate-only 治理:host 侧跑同步 hard-path 拒 + 密钥检测,签回执,返回放行哨兵;
        真正落盘留在 Seatbelt 子进程(Codex 式 workspace-write 自动应用)。request()/execute_sync()
        对 write_file/edit_file 都走这里,不进 _execute(broker 绝不替子进程写文件)。

        - evaluator decision==deny(系统路径命中 hard-path 拒名单)→ 拒,不签回执(无副作用)。
        - secret_pattern 命中 → fail-closed 拒(同步路径无法 await 确认;诚实告知模型),不签回执。
        - 其余(含因档位/软规则本应 ask 的)→ 自动放行:签回执(治理铁证)+ 返回放行哨兵。
          (与 run_command 同步桥跳过②审批一致 = Codex 式自动应用;绝不把普通写当 deny。)
        """
        meta = self._gate.evaluate_sync(action, args)
        if meta is not None:
            if meta.decision == "deny":
                return meta.reason or f"{action} 被硬规则拒绝。"
            if meta.secret_pattern or (meta.trigger or "").startswith("secret:"):
                return (
                    f"⚠ 可能含密钥({meta.secret_pattern or '?'})—— 已拒绝写入。"
                    "请去掉密钥后重试,或请用户显式放行该写入。"
                )
        self.last_receipt = self._signer.sign(
            action=action, args=args, result=_files.WRITE_APPROVED_SENTINEL, exit_code=0,
        )
        return _files.WRITE_APPROVED_SENTINEL

    def _execute(self, action: str, args: dict[str, Any],
                 run_ctx: Any = None, *, _gated: bool = False,
                 allow_network: bool = False) -> tuple[Any, int | None]:
        """⚠️ 内部裸执行 —— 仅供 request() 调用。绝不可从外部/测试直接调:
        它跳过 egress 校验、审批裁决与 Receipt 签发,直接产生真副作用。
        所有 broker-gated 动作必须经 request() 入口(它做完整 gating)。

        _gated:keyword-only 哨兵。request() 管线内调用传 True。
        registry dispatch 分支要求 _gated=True;否则 raise PermissionError(fail-closed,
        防止同步桥/外部路径绕过 egress/审批/回执直接触发带 dispatch 的注册能力)。

        P2 registry dispatch(优先级最高):
        - registry.get(action) 存在 且 cap.dispatch 非 None → 调 cap.dispatch(args, run_ctx)。
          (要求 _gated=True,否则 PermissionError)
        - registry.get(action) 存在 但 dispatch=None → 走既有 if/elif 内置实现。
        - action 不在 registry(含 registry=None 情况)→ 走既有 if/elif 内置实现。
        """
        # ─── P2:registry dispatch(cap 存在 + dispatch 非 None)────────────────
        # getattr 防御：object.__new__ 绕过 __init__ 的旧测试路径没有 _registry 属性
        _registry = getattr(self, "_registry", None)
        if _registry is not None:
            try:
                cap = _registry.get(action)
                if cap.dispatch is not None:
                    if not _gated:
                        raise PermissionError(
                            f"dispatch 能力 {action!r} 只允许经 broker.request() 管线执行"
                            "(egress/审批/回执不可旁路)"
                        )
                    result = cap.dispatch(args, run_ctx)
                    return result, None
                # cap 存在但 dispatch=None → fall through 到既有实现
            except KeyError:
                # 不在 registry → fall through 到既有实现
                pass
        # ─── 既有 if/elif 内置实现 ──────────────────────────────────────────
        if action == "run_command":
            # allow_network 由 gating 层(request)在审批通过后传入:命令需联网且已批准 → 开网阀。
            return _shell.run_command(args.get("command", ""), workspace=self._workspace,
                                      allow_network=allow_network)
        if action == "web_search":
            return _web.web_search(args.get("query", ""), int(args.get("limit", 5))), None
        if action == "web_extract":
            return _web.web_extract(args.get("url", "")), None
        # 计算机控制(浏览器):走注入的 BrowserController(或模块级单例 fallback);
        # 独占线程跑 sync Playwright,绕开 asyncio loop 线程冲突;懒启动。
        if action.startswith("browser_"):
            if self._browser_controller is not None:
                ctrl = self._browser_controller
            else:
                from argos import browser as _browser
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
        # MCP 外部工具:转给注入的 McpManager(或模块级单例 fallback);
        # 懒连 ~/.argos/mcp.json 的 stdio server。
        if action == "mcp_call":
            if self._mcp_manager is not None:
                mgr = self._mcp_manager
            else:
                from argos import mcp_native
                mgr = mcp_native.get_manager()
            arguments = args.get("arguments")
            if not isinstance(arguments, dict):
                arguments = {}
            return mgr.call(args.get("server", ""), args.get("tool", ""), arguments), None
        # OS 级计算机控制(P6a §10):经 ComputerExecutor 执行真实系统调用。
        # 诚实性:屏幕/鼠标是全局资源,Seatbelt 关不住;用"审批+Ledger+high risk"治理。
        # ARGOS_COMPUTER_USE=1 未设置时 ComputerExecutor 自身返回诚实禁止消息。
        if action.startswith("computer_"):
            from argos.perception.actions import ComputerAction
            from argos.perception.executor import ComputerExecutor
            # 将 broker action 名(如 "computer_click")映射到 ComputerAction.kind
            kind = action[len("computer_"):]   # "click" / "screenshot" / …
            try:
                ca = ComputerAction(
                    kind=kind,  # type: ignore[arg-type]
                    x=int(args["x"]) if "x" in args else None,
                    y=int(args["y"]) if "y" in args else None,
                    text=str(args["text"]) if "text" in args else None,
                    app=str(args["app"]) if "app" in args else None,
                )
            except (ValueError, TypeError) as exc:
                return f"computer 动作参数校验失败: {exc}", None
            # auto_detect_scale=True:真实 dispatch 路径惰性探测 Retina backing scale,
            # 让点击/滚动坐标(物理像素)正确换算为 AppleScript 逻辑点(2x 屏不再偏移)。
            result = ComputerExecutor(auto_detect_scale=True).dispatch(ca)
            # 截图:stash 工件(path, size)供 loop 取去挂图像(视觉回路)。非截图动作不动。
            if result.ok and getattr(result, "artifact_path", None):
                self.last_computer_artifact = (
                    result.artifact_path, getattr(result, "size", None),
                )
            # 诚实返回:ok=True → 人话摘要;ok=False → 原因串(含权限指引)
            return result.detail, (0 if result.ok else 1)
        # LSP 工具派发(spec §2.8):host 侧 LspManager 派发到对应 language server。
        if action.startswith("lsp_"):
            import json as _json
            from argos import lsp as _lsp
            from argos.lsp.tools import (
                lsp_definition_gated as _lsp_def,
                lsp_references_gated as _lsp_ref,
                lsp_hover_gated as _lsp_hov,
                lsp_document_symbols_gated as _lsp_dsym,
                lsp_workspace_symbols_gated as _lsp_wsym,
                lsp_diagnostics_gated as _lsp_diag,
            )
            mgr = _lsp.get_manager()
            workspace = self._workspace if self._workspace is not None else Path.cwd()
            kwargs: dict = {"manager": mgr, "workspace": workspace}
            if action == "lsp_definition":
                file = args.get("file", "")
                sname = _resolve_lsp_server(file=file, manager=mgr)
                if sname is None:
                    return _json.dumps({"error": f"no lsp server configured for {Path(file).suffix or file!r}"}), None
                return _lsp_def(
                    server_name=sname,
                    file=file,
                    line=int(args.get("line", 1)),
                    col=int(args.get("col", 1)),
                    **kwargs,
                ), None
            if action == "lsp_references":
                file = args.get("file", "")
                sname = _resolve_lsp_server(file=file, manager=mgr)
                if sname is None:
                    return _json.dumps({"error": f"no lsp server configured for {Path(file).suffix or file!r}"}), None
                return _lsp_ref(
                    server_name=sname,
                    file=file,
                    line=int(args.get("line", 1)),
                    col=int(args.get("col", 1)),
                    include_declaration=bool(args.get("include_declaration", True)),
                    **kwargs,
                ), None
            if action == "lsp_hover":
                file = args.get("file", "")
                sname = _resolve_lsp_server(file=file, manager=mgr)
                if sname is None:
                    return _json.dumps({"error": f"no lsp server configured for {Path(file).suffix or file!r}"}), None
                return _lsp_hov(
                    server_name=sname,
                    file=file,
                    line=int(args.get("line", 1)),
                    col=int(args.get("col", 1)),
                    **kwargs,
                ), None
            if action == "lsp_document_symbols":
                file = args.get("file", "")
                sname = _resolve_lsp_server(file=file, manager=mgr)
                if sname is None:
                    return _json.dumps({"error": f"no lsp server configured for {Path(file).suffix or file!r}"}), None
                return _lsp_dsym(
                    server_name=sname,
                    file=file,
                    **kwargs,
                ), None
            if action == "lsp_workspace_symbols":
                # workspace/symbol は file なし:設定済み最初の server を使う
                sname = _resolve_lsp_server(file=None, manager=mgr)
                if sname is None:
                    return _json.dumps({"error": "no lsp server configured"}), None
                return _lsp_wsym(
                    server_name=sname,
                    query=args.get("query", ""),
                    **kwargs,
                ), None
            if action == "lsp_diagnostics":
                file = args.get("file", "")
                sname = _resolve_lsp_server(file=file, manager=mgr)
                if sname is None:
                    return _json.dumps({"error": f"no lsp server configured for {Path(file).suffix or file!r}"}), None
                return _lsp_diag(
                    server_name=sname,
                    file=file,
                    **kwargs,
                ), None
        # 文件写:host 侧"执行" = gate-only 放行哨兵(真正落盘在 Seatbelt 子进程的 wrapper 内)。
        # 正常路径 request()/execute_sync() 已在入口拦截 write_file 做完整 hard-path/密钥/回执治理,
        # 不会走到这里;此分支兜底直调 _execute 的路径(如旧 e2e ungated broker_handler)。
        if action in _FILE_WRITE_ACTIONS:
            return _files.WRITE_APPROVED_SENTINEL, 0
        # 未知 action 已被 request 顶部挡掉;此处兜底诚实返回。
        return f"错误:动作 {action!r} 暂未实现 host 执行。", None

    @staticmethod
    def _describe(action: str, args: dict[str, Any]) -> str:
        if action == "run_command":
            cmd = args.get("command", "")
            if _shell.command_needs_network(cmd):
                return f"执行命令(需联网,将临时开出网阀){cmd}"
            return f"执行命令 {cmd}"
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
