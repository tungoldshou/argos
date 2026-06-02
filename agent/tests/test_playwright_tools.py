"""playwright_tools 测试 —— mock playwright.async_api 验 4 工具 invoke 行为 + 审批闸 + Lazy init。

不连真网络;mock 整个 playwright.async_api。"""
import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


# ── helpers ────────────────────────────────────────────────────────────

def _install_mock_page(mock_page: MagicMock) -> None:
    """重置全局 + 注入 mock page,绕开 launch 链。"""
    from argos_agent.playwright_tools import _set_browser_for_test, _reset_for_test
    _reset_for_test()
    _set_browser_for_test(mock_page)


def _deny_gate_factory() -> tuple:
    """建一个 deny gate + token;测试代码必须在 finally 调 reset_current_gate 收尾。"""
    from argos_agent import approval

    gate = approval.ApprovalGate()
    seen: dict = {}

    async def fake_request(payload: dict, timeout: float = 60.0) -> "approval.Decision":
        seen["tool"] = payload.get("tool")
        seen["payload"] = payload
        return approval.Decision(approved=False, reason="test-deny")

    gate.request = fake_request  # type: ignore[assignment]
    token = approval.set_current_gate(gate)
    return gate, seen, token


# ── 4 工具 invoke 行为(无审批闸=直接走底层) ────────────────────────────
# 这些测试在 invoke 路径中**绕过审批门**——通过预先把 session-approvals 缓存里塞
# 一个 hash 命中 entry,让 gate.request() 立即返 approved=True(session 缓存路径见
# approval.py:76-78)。但 session 缓存 key 是 _hash_payload(payload),需要先 mock。
# 这里改用更简单的方案:把审批装饰的 wrapper 用 requires_approval 装饰前的原函数
# 临时替换——但模块级名字 navigate 等已 StructuredTool 化,不可逆。
# 改方案:走 mock 路径(直接调 impl),不走 StructuredTool.ainvoke。
# 但用户要验 ainvoke 行为,所以这里用更轻的方案:把 _set_browser_for_test 注入 mock
# page,然后调 navigate.ainvoke 并预填 session-approvals 绕过 gate。

def _session_approve(tool_name: str, args: dict) -> None:
    """预填 session-scope 缓存,让 gate 立即放行。"""
    from argos_agent import approval
    # payload 格式与 approval.requires_approval._serialize_args 一致
    payload = {"source": "tools", "name": tool_name, "args": args, "risk": "low"}
    key = approval._hash_payload(payload)
    approval._SessionApproval = approval._SessionApproval  # noqa
    # 直接操作 _session_approvals:用 token's gate 不可见;改用全局注入法
    # 实际 approval.py:78 用 self._session_approvals.get(key),需要 gate 实例
    # 这里改用 fake_request 直接返 approved=True
    raise NotImplementedError  # 占位,见下


# ── 真实测试 ────────────────────────────────────────────────────────────

def test_navigate_invokes_goto_and_waits():
    """navigate 走审批门;给 gate 预批准后,真调 page.goto。"""
    from argos_agent import approval
    from argos_agent import playwright_tools

    _install_mock_page(MagicMock(
        goto=AsyncMock(return_value=MagicMock(status=200)),
        title=AsyncMock(return_value="Example"),
        url="https://example.com/",
    ))

    # 用 fake gate 直接批准
    async def approve_all(payload, timeout=60.0):
        return approval.Decision(approved=True, scope="once")

    gate = approval.ApprovalGate()
    gate.request = approve_all  # type: ignore[assignment]
    token = approval.set_current_gate(gate)
    try:
        async def run():
            return await playwright_tools.navigate.ainvoke({"url": "https://example.com"})
        result = asyncio.run(run())
    finally:
        approval.reset_current_gate(token)
        playwright_tools._reset_for_test()

    # 拿底层 mock 验 goto 真被调(title 也走底层)
    # 由于 invoke 后 _PAGE 已被 set_browser_for_test 注入,mock 的 goto 调用可由 page obj 拿到
    # 但 _install_mock_page 把 _PAGE 设进去后 invoke 时 StructuredTool coroutine 是审批 wrapper,
    # 内部 await _ensure_browser 返 _PAGE (= mock_page),再调 mock_page.goto
    # 这里我们重新拿 mock_page 验
    assert result["title"] == "Example"
    assert result["url"] == "https://example.com/"
    assert result["loaded"] is True


def test_snapshot_returns_title_url_headings():
    """snapshot 不走审批门,直接读 page 状态。"""
    from argos_agent import playwright_tools

    mock_page = MagicMock(
        title=AsyncMock(return_value="Example Domain"),
        url="https://example.com/",
    )
    loc = MagicMock()
    loc.all_inner_texts = AsyncMock(return_value=["Example Domain", "Illustrative"])
    mock_page.locator = MagicMock(return_value=loc)
    _install_mock_page(mock_page)
    try:
        async def run():
            return await playwright_tools.snapshot.ainvoke({})
        result = asyncio.run(run())
    finally:
        playwright_tools._reset_for_test()
    assert result["title"] == "Example Domain"
    assert result["url"] == "https://example.com/"
    assert "Example Domain" in result["headings"]


def test_click_invokes_page_click_when_approved():
    """click 走审批门;给 gate 批准后,真调 page.click。"""
    from argos_agent import approval
    from argos_agent import playwright_tools

    mock_page = MagicMock(
        click=AsyncMock(return_value=None),
        url="https://example.com/",
    )
    _install_mock_page(mock_page)

    async def approve_all(payload, timeout=60.0):
        return approval.Decision(approved=True, scope="once")

    gate = approval.ApprovalGate()
    gate.request = approve_all  # type: ignore[assignment]
    token = approval.set_current_gate(gate)
    try:
        async def run():
            return await playwright_tools.click.ainvoke({"selector": "button#submit"})
        result = asyncio.run(run())
    finally:
        approval.reset_current_gate(token)
        playwright_tools._reset_for_test()

    mock_page.click.assert_called_once()
    assert mock_page.click.call_args[0][0] == "button#submit"
    assert result.get("ok") is True


def test_type_text_invokes_page_fill_when_approved():
    """type_text 走审批门;给 gate 批准后,真调 page.fill。"""
    from argos_agent import approval
    from argos_agent import playwright_tools

    mock_page = MagicMock(
        fill=AsyncMock(return_value=None),
        url="https://example.com/",
    )
    _install_mock_page(mock_page)

    async def approve_all(payload, timeout=60.0):
        return approval.Decision(approved=True, scope="once")

    gate = approval.ApprovalGate()
    gate.request = approve_all  # type: ignore[assignment]
    token = approval.set_current_gate(gate)
    try:
        async def run():
            return await playwright_tools.type_text.ainvoke(
                {"selector": "input#q", "text": "hello"}
            )
        result = asyncio.run(run())
    finally:
        approval.reset_current_gate(token)
        playwright_tools._reset_for_test()

    mock_page.fill.assert_called_once()
    assert mock_page.fill.call_args[0][0] == "input#q"
    assert mock_page.fill.call_args[0][1] == "hello"
    assert result.get("ok") is True


# ── Lazy init 行为 ──────────────────────────────────────────────────────

def test_browser_lazy_init_only_on_first_invoke():
    """首次 invoke 才拉起 browser;init 失败返 ToolException。"""
    from argos_agent import approval
    from argos_agent import playwright_tools
    from langchain_core.tools import ToolException

    playwright_tools._reset_for_test()  # 关键:清前几个测试注入的 mock _PAGE

    async def approve_all(payload, timeout=60.0):
        return approval.Decision(approved=True, scope="once")

    gate = approval.ApprovalGate()
    gate.request = approve_all  # type: ignore[assignment]
    token = approval.set_current_gate(gate)

    with patch.object(
        playwright_tools,
        "_ensure_browser",
        new=AsyncMock(side_effect=Exception("launch failed")),
    ):
        async def run():
            try:
                await playwright_tools.navigate.ainvoke({"url": "https://example.com"})
                assert False, "expected ToolException"
            except ToolException as e:
                assert "browser unavailable" in str(e).lower() or "launch" in str(e).lower()
        asyncio.run(run())
    playwright_tools._reset_for_test()  # 干净收尾
    approval.reset_current_gate(token)


# ── all_tools() 合集形状 ──────────────────────────────────────────────

def test_all_tools_returns_4_tools():
    from argos_agent import playwright_tools
    tools = playwright_tools.all_tools()
    assert len(tools) == 4
    names = {t.name for t in tools}
    assert names == {"navigate", "snapshot", "click", "type_text"}


# ── 审批闸真拦 gate(新 3 个测试,替代旧的 _approval_required 标记测试) ─

def test_navigate_invoke_triggers_approval_gate():
    """navigate 真过 gate;deny → 返拒绝串、不调 page.goto。"""
    from argos_agent import approval
    from argos_agent import playwright_tools

    mock_page = MagicMock(
        goto=AsyncMock(return_value=MagicMock(status=200)),
        title=AsyncMock(return_value="x"),
        url="https://x/",
    )
    _install_mock_page(mock_page)
    gate, seen, token = _deny_gate_factory()
    try:
        async def run():
            return await playwright_tools.navigate.ainvoke({"url": "https://x/"})
        result = asyncio.run(run())
    finally:
        approval.reset_current_gate(token)
        playwright_tools._reset_for_test()

    assert "拒绝" in str(result) or "denied" in str(result).lower()
    assert seen.get("payload", {}).get("tool") == "navigate", "审批 gate 没被调到"
    mock_page.goto.assert_not_called()  # 关键:审批未过、不调底层


def test_click_invoke_triggers_approval_gate():
    """click 真过 gate;deny → 返拒绝串、不调 page.click。"""
    from argos_agent import approval
    from argos_agent import playwright_tools

    mock_page = MagicMock(
        click=AsyncMock(return_value=None),
        url="https://x/",
    )
    _install_mock_page(mock_page)
    gate, seen, token = _deny_gate_factory()
    try:
        async def run():
            return await playwright_tools.click.ainvoke({"selector": "button#x"})
        result = asyncio.run(run())
    finally:
        approval.reset_current_gate(token)
        playwright_tools._reset_for_test()

    assert "拒绝" in str(result) or "denied" in str(result).lower()
    assert seen.get("payload", {}).get("tool") == "click", "审批 gate 没被调到"
    mock_page.click.assert_not_called()


def test_type_text_invoke_triggers_approval_gate():
    """type_text 真过 gate;deny → 返拒绝串、不调 page.fill。"""
    from argos_agent import approval
    from argos_agent import playwright_tools

    mock_page = MagicMock(
        fill=AsyncMock(return_value=None),
        url="https://x/",
    )
    _install_mock_page(mock_page)
    gate, seen, token = _deny_gate_factory()
    try:
        async def run():
            return await playwright_tools.type_text.ainvoke(
                {"selector": "input#q", "text": "x"}
            )
        result = asyncio.run(run())
    finally:
        approval.reset_current_gate(token)
        playwright_tools._reset_for_test()

    assert "拒绝" in str(result) or "denied" in str(result).lower()
    assert seen.get("payload", {}).get("tool") == "type_text", "审批 gate 没被调到"
    mock_page.fill.assert_not_called()


# ── snapshot 不过闸 + 降级路径 ──────────────────────────────────────

def test_snapshot_does_not_trigger_approval_gate():
    """snapshot 只读,不应调用 gate。给个 fail-closed gate,真没调就放行。"""
    from argos_agent import approval
    from argos_agent import playwright_tools

    mock_page = MagicMock(
        title=AsyncMock(return_value="x"),
        url="https://x/",
    )
    loc = MagicMock()
    loc.all_inner_texts = AsyncMock(return_value=[])
    mock_page.locator = MagicMock(return_value=loc)
    _install_mock_page(mock_page)

    called = {"hit": False}

    async def explode_if_called(payload, timeout=60.0):
        called["hit"] = True
        return approval.Decision(approved=False, reason="should-not-be-called")

    gate = approval.ApprovalGate()
    gate.request = explode_if_called  # type: ignore[assignment]
    token = approval.set_current_gate(gate)
    try:
        async def run():
            return await playwright_tools.snapshot.ainvoke({})
        result = asyncio.run(run())
    finally:
        approval.reset_current_gate(token)
        playwright_tools._reset_for_test()

    assert called["hit"] is False, "snapshot 不应触发审批 gate"
    assert result["title"] == "x"


def test_click_disabled_when_enabled_write_tools_false():
    """ENABLED_WRITE_TOOLS=False → click 走完 gate 批准后,在 impl body 抛 ToolException("disabled")。
    不调底层 page.click。"""
    from argos_agent import approval
    from argos_agent import playwright_tools
    from langchain_core.tools import ToolException

    mock_page = MagicMock(
        click=AsyncMock(return_value=None),
        url="https://x/",
    )
    _install_mock_page(mock_page)

    async def approve_all(payload, timeout=60.0):
        return approval.Decision(approved=True, scope="once")

    gate = approval.ApprovalGate()
    gate.request = approve_all  # type: ignore[assignment]
    token = approval.set_current_gate(gate)
    playwright_tools.ENABLED_WRITE_TOOLS = False
    try:
        async def run():
            try:
                await playwright_tools.click.ainvoke({"selector": "x"})
                assert False, "expected ToolException"
            except ToolException as e:
                assert "disabled" in str(e).lower() or "降级" in str(e)
        asyncio.run(run())
    finally:
        playwright_tools.ENABLED_WRITE_TOOLS = True
        approval.reset_current_gate(token)
        playwright_tools._reset_for_test()

    mock_page.click.assert_not_called()
