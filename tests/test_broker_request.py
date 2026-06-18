"""Phase 3:CapabilityBroker.request —— egress→审批→host 执行→签 Receipt→fail-closed(契约 §5)。"""
from __future__ import annotations

import asyncio

import pytest

from argos.approval import ApprovalGate, ApprovalLevel
from argos.sandbox.broker import BrokerResult, CapabilityBroker
from argos.sandbox.egress import EgressPolicy
from argos.tools.receipts import ReceiptSigner


def _broker(level=ApprovalLevel.AUTO, search_hosts=None):
    gate = ApprovalGate(level=level)
    egress = EgressPolicy(llm_hosts={"api.minimaxi.com"},
                          search_hosts=search_hosts or {"duckduckgo.com"}, mcp_hosts=set())
    signer = ReceiptSigner(key=b"host-only-key")
    return CapabilityBroker(gate=gate, egress=egress, signer=signer)


def test_broker_passes_workspace_to_run_command(monkeypatch, tmp_path):
    """workspace 分叉 bug 回归:broker 带 workspace 时,run_command 必须用【同一个 ws】,
    而非 shell 自己的 _ws()(否则 --project 模式 run_command 落默认 workspace、write_file
    落项目目录,脚本读不到刚写的文件)。"""
    captured = {}

    def fake_run(command, *, workspace=None):
        captured["workspace"] = workspace
        return ("ok", 0)

    monkeypatch.setattr("argos.tools.shell.run_command", fake_run)
    gate = ApprovalGate(level=ApprovalLevel.AUTO)
    egress = EgressPolicy(llm_hosts=set(), search_hosts=set(), mcp_hosts=set())
    broker = CapabilityBroker(gate=gate, egress=egress, signer=ReceiptSigner(key=b"k"),
                              workspace=tmp_path)
    broker._execute("run_command", {"command": "python app.py"})
    assert captured["workspace"] == tmp_path   # 用 broker 的 ws,不回退默认


def test_broker_workspace_defaults_none_back_compat(monkeypatch):
    """不传 workspace 时维持旧行为:workspace=None 传给 shell(由 shell._ws() 解析)。"""
    captured = {}

    def fake_run(command, *, workspace=None):
        captured["workspace"] = workspace
        return ("ok", 0)

    monkeypatch.setattr("argos.tools.shell.run_command", fake_run)
    gate = ApprovalGate(level=ApprovalLevel.AUTO)
    egress = EgressPolicy(llm_hosts=set(), search_hosts=set(), mcp_hosts=set())
    broker = CapabilityBroker(gate=gate, egress=egress, signer=ReceiptSigner(key=b"k"))
    broker._execute("run_command", {"command": "ls"})
    assert captured["workspace"] is None


async def _approve_pending_confirm(gate: ApprovalGate, kind: str = "once") -> None:
    """C1:run_command 即便 AUTO 也强制 CONFIRM → 它会挂起等 respond。
    本 helper 轮询 pending 并回 once 放行(模拟用户点'允许')。

    xdist 并行时 worker 可能负载高,用较长轮询窗口(最多 5s)防止在极端 CPU 争抢下因
    1s 超时窗口耗尽而误失败。每次 sleep 极短(5ms)不影响正常情况响应时间。
    """
    for _ in range(1000):   # 最多 5s(1000 × 5ms);正常 <100ms 就拿到
        pend = gate.pending()
        if pend:
            gate.respond(pend[0].call_id, kind)
            return
        await asyncio.sleep(0.005)


@pytest.mark.asyncio
async def test_run_command_executes_and_signs_after_confirm():
    """C1:run_command 在 AUTO 档也强制确认;用户确认后才执行 + 签 Receipt。"""
    br = _broker(level=ApprovalLevel.AUTO)
    approver = asyncio.create_task(_approve_pending_confirm(br._gate))
    res = await br.request("run_command", {"command": "echo hi"})
    await approver
    assert isinstance(res, str)
    assert "hi" in res and "exit_code=0" in res
    # 副产物:签了 Receipt(broker 暴露最近回执供 loop 投事件)
    rec = br.last_receipt
    assert rec is not None and rec.action == "run_command"
    assert br._signer.verify(rec) is True


@pytest.mark.asyncio
async def test_denied_returns_fail_closed_string_not_raise():
    br = _broker(level=ApprovalLevel.OBSERVE)  # OBSERVE → 一律 deny
    res = await br.request("run_command", {"command": "echo hi"})
    assert isinstance(res, str)
    assert "拒绝" in res    # fail-closed 拒绝串,不抛异常


@pytest.mark.asyncio
async def test_web_extract_allows_public_denies_internal():
    """web_extract 目标 URL 由 agent 动态选(egress_hosts="*")→ 放行任意【公网】host(不再卡白名单),
    私网/回环/云元数据仍被 SSRF 硬挡(2026-06-18 用户拍板)。出网问责靠 SSRF+审批+回执,非静态白名单。"""
    br = _broker(level=ApprovalLevel.AUTO, search_hosts={"duckduckgo.com"})
    # 公网 host:egress 裁决层放行(不打真网,只验裁决)
    assert br._egress_deny_reason("web_extract", {"url": "https://news.example.com/x"}) is None
    # 私网/回环/云元数据:egress 裁决层即拒(SSRF 第一层)
    for bad in ("http://169.254.169.254/latest/meta-data/", "http://127.0.0.1:8080/admin",
                "http://10.0.0.5/", "http://metadata.google.internal/"):
        assert br._egress_deny_reason("web_extract", {"url": bad}) is not None, bad
    # 端到端:私网 url 经 request() 被拒,不触发网络、不签回执
    res = await br.request("web_extract", {"url": "http://169.254.169.254/"})
    assert "SSRF" in res or "私网" in res or "内网" in res
    assert br.last_receipt is None


@pytest.mark.asyncio
async def test_unknown_action_rejected():
    br = _broker(level=ApprovalLevel.AUTO)
    res = await br.request("rm_rf_everything", {})
    assert "未知" in res or "不支持" in res


@pytest.mark.asyncio
async def test_broker_result_is_frozen_dataclass():
    """BrokerResult 是冻结 dataclass(契约 §5 不变量)。"""
    import dataclasses
    from argos.tools.receipts import Receipt
    # 构造一个假 Receipt
    signer = ReceiptSigner(key=b"test")
    r = signer.sign(action="web_search", args={}, result="x", exit_code=None)
    br_result = BrokerResult(value="hello", receipt=r)
    assert dataclasses.is_dataclass(br_result)
    assert BrokerResult.__dataclass_params__.frozen is True
    assert br_result.value == "hello"
    assert br_result.receipt is r


@pytest.mark.asyncio
async def test_no_receipt_when_denied():
    """拒绝时 last_receipt 不被更新(不签名 = 无副作用回执)。"""
    br = _broker(level=ApprovalLevel.OBSERVE)
    old_receipt = br.last_receipt  # None 初始
    await br.request("run_command", {"command": "echo hi"})
    assert br.last_receipt is old_receipt  # 还是 None,未签


# ── I3:web_search 出口 fail-closed 校验(provider host 必须在 search_hosts)─────────
@pytest.mark.asyncio
async def test_web_search_egress_denied_when_provider_host_not_allowed(monkeypatch):
    """I3:活跃 provider 出口 host 不在 search_hosts → web_search 被 egress 拒(fail-closed),
    绝不静默放行。"""
    monkeypatch.delenv("TAVILY_API_KEY", raising=False)  # → DDGS provider, host=duckduckgo.com
    # search_hosts 故意只放别的域,不含 duckduckgo.com
    br = _broker(level=ApprovalLevel.AUTO, search_hosts={"someother.example"})
    res = await br.request("web_search", {"query": "x"})
    assert "egress" in res or "不在允许" in res
    assert br.last_receipt is None  # 被 egress 拦掉,没执行没签回执


@pytest.mark.asyncio
async def test_web_search_egress_allowed_when_provider_host_listed(monkeypatch):
    """I3:provider 出口 host 在 search_hosts → 放行进入审批/执行(此处 monkeypatch 真搜索)。"""
    monkeypatch.delenv("TAVILY_API_KEY", raising=False)  # DDGS → duckduckgo.com

    import argos.web as _w
    monkeypatch.setattr(_w, "search", lambda q, limit=5: {
        "success": True, "results": [{"title": "t", "url": "u", "snippet": "s"}],
    })
    br = _broker(level=ApprovalLevel.AUTO, search_hosts={"duckduckgo.com"})
    res = await br.request("web_search", {"query": "x", "limit": 3})
    assert "egress" not in res and "不在允许" not in res
    assert br.last_receipt is not None and br.last_receipt.action == "web_search"


# ── I4:broker gating 走 request() 端到端(deny 路径无 receipt)──────────────────────
@pytest.mark.asyncio
async def test_network_action_denied_at_observe_through_request():
    """I4:OBSERVE 档下网络动作经 request() 被审批拒 → 返回拒绝串、无 Receipt。
    证明 egress→approval→receipt 真把网络动作 gate 住(非 _execute 裸调)。"""
    br = _broker(level=ApprovalLevel.OBSERVE, search_hosts={"duckduckgo.com"})
    res = await br.request("web_search", {"query": "x"})
    assert "拒绝" in res
    assert br.last_receipt is None  # deny → 不执行不签回执


@pytest.mark.asyncio
async def test_take_receipt_returns_and_clears():
    """I2:take_receipt() 返回并清空 last_receipt(loop 据此投 per-step ToolReceipt)。"""
    br = _broker(level=ApprovalLevel.AUTO)
    approver = asyncio.create_task(_approve_pending_confirm(br._gate))
    await br.request("run_command", {"command": "echo hi"})
    await approver
    assert br.last_receipt is not None
    rec = br.take_receipt()
    assert rec is not None and rec.action == "run_command"
    assert br.last_receipt is None          # 已清空
    assert br.take_receipt() is None        # 再取无新回执


@pytest.mark.asyncio
async def test_run_command_forced_confirm_even_in_auto():
    """C1:run_command 在 AUTO 档也强制确认 —— 没有挂起的 respond 就超时 fail-closed 拒。
    用极短 timeout 经 gate 验证它确实进了 CONFIRM 等待(而非 AUTO 立即放行)。"""
    import argos.sandbox.broker as _bk
    gate = ApprovalGate(level=ApprovalLevel.AUTO)
    egress = EgressPolicy(llm_hosts=set(), search_hosts={"duckduckgo.com"}, mcp_hosts=set())
    signer = ReceiptSigner(key=b"k")
    br = CapabilityBroker(gate=gate, egress=egress, signer=signer)

    # monkeypatch gate.request 记录它被调用时的 level —— 应是 CONFIRM 而非 AUTO。
    seen = {}

    async def fake_request(action, args, *, description, risk, timeout=60.0):
        seen["level"] = gate.level
        from argos.approval import Decision
        return Decision(kind="deny", reason="测试拒绝")

    gate.request = fake_request  # type: ignore[assignment]
    res = await br.request("run_command", {"command": "echo hi"})
    assert seen["level"] is ApprovalLevel.CONFIRM, "run_command 在 AUTO 档应被强制降到 CONFIRM"
    assert gate.level is ApprovalLevel.AUTO, "裁决后应恢复原档,不污染 session"
    assert "拒绝" in res
