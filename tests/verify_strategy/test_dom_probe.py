from __future__ import annotations

import asyncio
import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch

from argos.verify.dom_probe import DomProber, DomProbeResult, _selector_to_text_hint
from argos.verify.strategy import generate, WorkspaceFacts


# ═══════════════════════════════════════════════════════
# ═══════════════════════════════════════════════════════

class TestDomProbeResultInvariants:

    def test_default_is_not_found_no_error(self) -> None:
        r = DomProbeResult()
        assert r.found is False
        assert r.error == ""
        assert r.text_excerpt == ""

    def test_found_true_ok(self) -> None:
        r = DomProbeResult(found=True, text_excerpt="hello", error="")
        assert r.found is True
        assert r.error == ""

    def test_error_not_found(self) -> None:
        r = DomProbeResult(found=False, text_excerpt="", error="浏览器不可用")
        assert r.found is False
        assert r.error != ""

    def test_frozen(self) -> None:
        r = DomProbeResult(found=True, text_excerpt="x", error="")
        with pytest.raises((AttributeError, TypeError)):
            r.found = False  # type: ignore[misc]


# ═══════════════════════════════════════════════════════
# ═══════════════════════════════════════════════════════

class TestDomProberNoBrowser:

    def setup_method(self) -> None:
        self.prober = DomProber(browser=None)

    def test_probe_returns_error(self) -> None:
        result = self.prober.probe("http://localhost", "h1")
        assert result.error != "", "browser=None 时必须返回 error"
        assert result.found is False

    def test_probe_with_no_url(self) -> None:
        result = self.prober.probe(None, "body")
        assert result.error != ""
        assert result.found is False

    def test_probe_with_expected_text_still_error(self) -> None:
        result = self.prober.probe("http://localhost", ".msg", expected_text="hello")
        assert result.error != ""
        assert result.found is False

    def test_never_passed_when_none(self) -> None:
        for selector in ("body", "h1", "#id", ".class", "div > span"):
            r = self.prober.probe("http://localhost:3000", selector)
            assert r.found is False, f"browser=None probe(selector={selector!r}) found 不应为 True"


# ═══════════════════════════════════════════════════════
# DomProber with monkeypatched BrowserController
# ═══════════════════════════════════════════════════════

def _make_mock_browser(*, nav_result: str = "已打开 http://localhost", snapshot_result: str = "") -> MagicMock:
    bc = MagicMock()
    bc.navigate.return_value = nav_result
    bc.snapshot.return_value = snapshot_result
    return bc


class TestDomProberFoundTrue:

    def test_found_with_expected_text_match(self) -> None:
        snapshot = "[页面] Test\n[URL] http://localhost\n\nWelcome hero-title new content"
        bc = _make_mock_browser(snapshot_result=snapshot)
        prober = DomProber(bc)
        result = prober.probe("http://localhost", ".hero-title", expected_text="new content")
        assert result.found is True
        assert result.error == ""

    def test_expected_text_found_has_excerpt(self) -> None:
        snapshot = "[页面] Test\n[URL] http://localhost\n\nhello world visible content here"
        bc = _make_mock_browser(snapshot_result=snapshot)
        prober = DomProber(bc)
        result = prober.probe("http://localhost", "h1", expected_text="visible content")
        assert result.found is True
        assert result.text_excerpt != "", "found=True 时 text_excerpt 不能空"

    def test_no_url_skips_navigate(self) -> None:
        snapshot = "[页面] Test\n[URL] http://localhost\n\nmsg element present target"
        bc = _make_mock_browser(snapshot_result=snapshot)
        prober = DomProber(bc)
        prober.probe(None, ".msg", expected_text="target")
        bc.navigate.assert_not_called()
        bc.snapshot.assert_called_once()


class TestDomProberWeakEvidence:

    def test_no_expected_text_never_passed(self) -> None:
        snapshot = "[页面] Test\n[URL] http://localhost\n\nWelcome headline here"
        bc = _make_mock_browser(snapshot_result=snapshot)
        prober = DomProber(bc)
        result = prober.probe("http://localhost", "h1.headline")
        assert result.found is False, (
            "反假绿：无 expected_text 时绝不能 found=True（弱证据路径）"
        )

    def test_no_expected_text_returns_unverifiable(self) -> None:
        snapshot = "[页面] Test\n[URL] http://localhost\n\nheadline present"
        bc = _make_mock_browser(snapshot_result=snapshot)
        prober = DomProber(bc)
        result = prober.probe("http://localhost", "h1.headline")
        assert result.error != "", (
            "无 expected_text 时探针结果必须是 unverifiable（error 非空）"
        )
        assert result.found is False

    def test_no_expected_text_hint_not_in_body_still_unverifiable(self) -> None:
        snapshot = "[页面] Test\n[URL] http://localhost\n\nno matching content at all"
        bc = _make_mock_browser(snapshot_result=snapshot)
        prober = DomProber(bc)
        result = prober.probe("http://localhost", "h1.nonexistent-element")
        assert result.error != "", "弱证据路径缺席也是 unverifiable，不是 failed"
        assert result.found is False

    def test_all_selectors_without_expected_text_never_passed(self) -> None:
        snapshot = "[页面] Test\n[URL] http://localhost\n\nbody h1 headline notification-badge hero-title msg"
        bc = _make_mock_browser(snapshot_result=snapshot)
        prober = DomProber(bc)
        for selector in ("h1.headline", "#notification-badge", ".hero-title", "div > span.msg"):
            result = prober.probe("http://localhost", selector)
            assert result.found is False, (
                f"反假绿：selector={selector!r} 无 expected_text 时 found 绝不能 True"
            )


class TestDomProberFoundFalse:

    def test_expected_text_mismatch_not_found(self) -> None:
        snapshot = "[页面] Test\n[URL] http://localhost\n\nhero-title present but wrong"
        bc = _make_mock_browser(snapshot_result=snapshot)
        prober = DomProber(bc)
        result = prober.probe("http://localhost", ".hero-title", expected_text="NEW HEADLINE")
        assert result.found is False
        assert result.error == "", "expected_text 不匹配是验证失败（failed），不是 error（unverifiable）"

    def test_expected_text_absent_is_failed_not_unverifiable(self) -> None:
        snapshot = "[页面] Test\n[URL] http://localhost\n\nsome content without target"
        bc = _make_mock_browser(snapshot_result=snapshot)
        prober = DomProber(bc)
        result = prober.probe("http://localhost", "h1", expected_text="this text is absent")
        assert result.found is False
        assert result.error == "", "强证据路径：expected_text 缺席应是 found=False+error=''，不是 unverifiable"


class TestDomProberError:

    def test_navigate_error_returns_error(self) -> None:
        bc = _make_mock_browser(nav_result="错误:浏览器启动失败(可能未安装 chromium)")
        prober = DomProber(bc)
        result = prober.probe("http://localhost", "body")
        assert result.error != "", "navigate 失败必须返回 error"
        assert result.found is False

    def test_snapshot_error_returns_error(self) -> None:
        bc = _make_mock_browser(snapshot_result="错误:页面快照失败")
        prober = DomProber(bc)
        result = prober.probe("http://localhost", "body")
        assert result.error != ""
        assert result.found is False

    def test_navigate_exception_returns_error(self) -> None:
        bc = MagicMock()
        bc.navigate.side_effect = RuntimeError("playwright crash")
        bc.snapshot.return_value = ""
        prober = DomProber(bc)
        result = prober.probe("http://localhost", "body")
        assert result.error != ""
        assert result.found is False

    def test_error_never_found_true(self) -> None:
        bc = _make_mock_browser(nav_result="错误:timeout")
        prober = DomProber(bc)
        for selector in ("body", "h1", "#id", ".class"):
            r = prober.probe("http://localhost", selector)
            if r.error:
                assert r.found is False, (
                    f"error 非空时 found 绝不能为 True（selector={selector!r}）"
                )


# ═══════════════════════════════════════════════════════
# ═══════════════════════════════════════════════════════

class TestSelectorToTextHint:

    @pytest.mark.parametrize("selector,expected_contains", [
        ("h1.headline", "headline"),
        ("#notification-badge", "notification-badge"),
        (".hero-title", "hero-title"),
        ("div > span.msg", "msg"),
        ("body", "body"),
        (".error-message", "error-message"),
    ])
    def test_extracts_meaningful_text(self, selector: str, expected_contains: str) -> None:
        hint = _selector_to_text_hint(selector)
        assert expected_contains in hint or hint in expected_contains, (
            f"selector={selector!r} → hint={hint!r}，不含 {expected_contains!r}"
        )

    def test_non_empty_for_common_selectors(self) -> None:
        for sel in ("body", "h1", "#id", ".class", "div.container"):
            assert _selector_to_text_hint(sel) != "", f"selector={sel!r} 应产非空提示"


# ═══════════════════════════════════════════════════════
# ═══════════════════════════════════════════════════════

class TestStrategyL3WithUrl:

    def test_dom_selector_hint_and_dom_url_hint_generates_l3(self) -> None:
        strats = generate(
            "update the webpage to show new content",
            workspace_facts=WorkspaceFacts(),
            capability_hints={"dom_selector": "h1.headline", "dom_url": "http://localhost:3000"},
        )
        l3 = [s for s in strats if s.level == "L3"]
        assert l3, "dom_selector + dom_url hint → 应生成 L3"
        assert "h1.headline" in (l3[0].target or "")
        assert "localhost:3000" in (l3[0].target or "")

    def test_dom_selector_hint_with_explicit_url_in_goal_generates_l3(self) -> None:
        strats = generate(
            "update the webpage at http://localhost:8080 to show the new headline",
            workspace_facts=WorkspaceFacts(),
            capability_hints={"dom_selector": ".headline"},
        )
        l3 = [s for s in strats if s.level == "L3"]
        assert l3, "goal 含显式 URL + dom_selector hint → 应生成 L3"
        assert "localhost:8080" in (l3[0].target or "")

    def test_dom_selector_hint_no_url_anywhere_no_l3(self) -> None:
        strats = generate(
            "update the webpage to show the new headline",
            workspace_facts=WorkspaceFacts(),
            capability_hints={"dom_selector": "h1.headline"},
        )
        l3 = [s for s in strats if s.level == "L3"]
        assert len(l3) == 0, f"无 URL 时不应生成 L3（诚实降级）: {l3}"

    def test_web_signal_without_dom_selector_no_l3(self) -> None:
        strats = generate(
            "render the frontend page at http://localhost:3000",
            workspace_facts=WorkspaceFacts(),
            capability_hints={"dom_url": "http://localhost:3000"},
        )
        l3 = [s for s in strats if s.level == "L3"]
        assert len(l3) == 0, f"无 dom_selector 不应生成 L3: {l3}"

    def test_l3_cmd_is_none(self) -> None:
        strats = generate(
            "update the webpage",
            workspace_facts=WorkspaceFacts(),
            capability_hints={"dom_selector": "body", "dom_url": "http://localhost"},
        )
        l3 = [s for s in strats if s.level == "L3"]
        if l3:
            assert l3[0].cmd is None, "L3 策略 cmd 必须是 None（探针路径）"

    def test_l3_before_l5(self) -> None:
        strats = generate(
            "update the webpage",
            workspace_facts=WorkspaceFacts(),
            capability_hints={"dom_selector": "body", "dom_url": "http://localhost"},
        )
        levels = [s.level for s in strats]
        if "L3" in levels:
            assert levels.index("L3") < levels.index("L5")

    def test_send_task_no_l3_even_with_hints(self) -> None:
        strats = generate(
            "send a notification to users",
            workspace_facts=WorkspaceFacts(),
            capability_hints={"dom_selector": "#badge", "dom_url": "http://localhost"},
        )
        l3 = [s for s in strats if s.level == "L3"]
        assert len(l3) == 0, f"发送类任务绝不生成 L3: {l3}"


# ═══════════════════════════════════════════════════════
# ═══════════════════════════════════════════════════════

class _CompletingModel:
    last_usage: dict = {}

    async def stream(self, messages, *, system="", system_dynamic=""):
        for ch in "完成了。":
            yield ch


class _FakeSandbox:
    def spawn(self, *, workspace, namespace, allow_workflow=True, read_only=False): ...
    def exec_code(self, code):
        from argos.sandbox.backend import ExecResult
        return ExecResult(stdout="", value_repr="", exc="")
    def close(self): ...


class _FakeStore:
    def append_event(self, sid, ev): ...
    def append_message(self, sid, **kw): return "m0"
    def ensure_session(self, sid, **kw): ...


class _FakeVerifier:
    last_usage: dict = {}

    def verify(self, verify_cmd, *, attempts=1):
        from argos.core.verify_gate import Verdict
        if verify_cmd:
            return Verdict.passed(detail="ok", verify_cmd=verify_cmd, attempts=attempts)
        return Verdict.unverifiable(detail="no cmd", tampered=[], attempts=attempts)


def _make_loop(*, dom_prober=None, verify_cmd=None, capability_hints=None):
    from argos.core.loop import AgentLoop, LoopConfig
    from argos.protocol.events import EventBus
    return AgentLoop(
        store=_FakeStore(),
        bus=EventBus(),
        sandbox=_FakeSandbox(),
        broker=None,
        model=_CompletingModel(),
        verifier=_FakeVerifier(),
        config=LoopConfig(verify_cmd=verify_cmd, max_steps=5, max_rounds=1),
        capability_hints=capability_hints,
        dom_prober=dom_prober,
    )


class TestLoopL3Wiring:

    def test_no_dom_prober_l3_skipped(self, tmp_path: Path) -> None:
        loop = _make_loop(
            dom_prober=None,
            capability_hints={"dom_selector": "h1", "dom_url": "http://localhost"},
        )
        loop._workspace = tmp_path
        cmd = loop._pick_strategy_cmd("update the webpage at http://localhost")
        assert loop._pending_l3_strategy is None, "DomProber=None 时不应挂起 L3 策略"

    def test_with_dom_prober_l3_pending(self, tmp_path: Path) -> None:
        fake_prober = DomProber(browser=None)
        loop = _make_loop(
            dom_prober=fake_prober,
            capability_hints={"dom_selector": ".headline", "dom_url": "http://localhost:3000"},
        )
        loop._workspace = tmp_path
        cmd = loop._pick_strategy_cmd(
            "update the webpage to show the new headline at http://localhost:3000"
        )
        assert cmd is None, "_pending_l3_strategy 时 cmd 仍 None（探针路径）"
        assert loop._pending_l3_strategy is not None, "L3 策略应被挂起"
        assert loop._pending_l3_strategy.level == "L3"
        assert loop._pending_l3_strategy.kind == "dom_assert"

    def test_explicit_verify_cmd_takes_priority(self, tmp_path: Path) -> None:
        fake_prober = DomProber(browser=None)
        loop = _make_loop(
            dom_prober=fake_prober,
            verify_cmd="pytest",
            capability_hints={"dom_selector": ".headline", "dom_url": "http://localhost"},
        )
        loop._workspace = tmp_path
        assert loop._verify_cmd == "pytest"
        assert loop._pending_l3_strategy is None

    def test_pending_l3_cleared_on_reset(self, tmp_path: Path) -> None:
        fake_prober = DomProber(browser=None)
        loop = _make_loop(dom_prober=fake_prober)
        loop._workspace = tmp_path
        loop._pending_l3_strategy = object()
        loop._reset_run_state()
        assert loop._pending_l3_strategy is None, "_reset_run_state 必须清空 _pending_l3_strategy"


# ═══════════════════════════════════════════════════════
# ═══════════════════════════════════════════════════════

class TestRunDomProbeVerdict:

    def _make_strategy(self, url: str = "http://localhost", selector: str = "h1") -> object:
        from argos.verify.strategy import VerifyStrategy
        return VerifyStrategy(
            level="L3", kind="dom_assert",
            cmd=None,
            target=f"{url}#{selector}",
            rationale_human="测试：检查元素存在",
            confidence=0.60,
        )

    def _run_verdict(
        self,
        prober: DomProber,
        strategy: object,
        *,
        expected_text: str = "",
    ) -> object:
        loop = _make_loop(dom_prober=prober)
        if expected_text:
            loop._pending_dom_expected_text = expected_text
        return asyncio.run(loop._run_dom_probe_verdict(strategy, attempt=1))

    def _make_strategy_with_expected(
        self,
        url: str = "http://localhost",
        selector: str = "h1",
        expected_text: str = "h1",
    ) -> object:
        from argos.verify.strategy import _l3_dom_assert
        hints: dict[str, str] = {
            "dom_url": url,
            "dom_selector": selector,
            "dom_expected_text": expected_text,
        }
        return _l3_dom_assert(hints)

    def test_found_true_yields_passed_with_expected_text(self) -> None:
        bc = _make_mock_browser(
            snapshot_result="[页面] T\n[URL] http://localhost\n\nh1 element here"
        )
        prober = DomProber(bc)
        strategy = self._make_strategy_with_expected(selector="h1", expected_text="h1 element")
        verdict = self._run_verdict(prober, strategy, expected_text="h1 element")
        assert verdict.status == "passed", f"有 expected_text 命中时 verdict 应为 passed，实际: {verdict}"

    def test_no_expected_text_yields_unverifiable(self) -> None:
        bc = _make_mock_browser(
            snapshot_result="[页面] T\n[URL] http://localhost\n\nh1 element here"
        )
        prober = DomProber(bc)
        strategy = self._make_strategy(selector="h1")
        verdict = self._run_verdict(prober, strategy)
        assert verdict.status == "unverifiable", (
            f"无 expected_text 时 verdict 应为 unverifiable（弱证据），实际: {verdict}"
        )

    def test_found_false_with_expected_text_yields_failed(self) -> None:
        bc = _make_mock_browser(
            snapshot_result="[页面] T\n[URL] http://localhost\n\nno matching content at all"
        )
        prober = DomProber(bc)
        strategy = self._make_strategy_with_expected(
            selector="h1", expected_text="nonexistent-xyz-abc"
        )
        verdict = self._run_verdict(prober, strategy, expected_text="nonexistent-xyz-abc")
        assert verdict.status == "failed", (
            f"expected_text 明确缺席时 verdict 应为 failed，实际: {verdict}"
        )

    def test_error_yields_unverifiable(self) -> None:
        bc = _make_mock_browser(nav_result="错误:浏览器启动失败(chromium 未安装)")
        prober = DomProber(bc)
        strategy = self._make_strategy()
        verdict = self._run_verdict(prober, strategy)
        assert verdict.status == "unverifiable", (
            f"error 非空时 verdict 应为 unverifiable，实际: {verdict}"
        )

    def test_error_never_passed(self) -> None:
        error_scenarios = [
            _make_mock_browser(nav_result="错误:timeout"),
            _make_mock_browser(snapshot_result="错误:snapshot 失败"),
        ]
        strategy = self._make_strategy()
        for bc in error_scenarios:
            prober = DomProber(bc)
            verdict = self._run_verdict(prober, strategy)
            assert verdict.status != "passed", (
                f"error 场景绝不应 passed，实际 status={verdict.status!r}"
            )

    def test_none_browser_yields_unverifiable(self) -> None:
        prober = DomProber(browser=None)
        strategy = self._make_strategy()
        verdict = self._run_verdict(prober, strategy)
        assert verdict.status == "unverifiable"
        assert verdict.status != "passed"

    def test_verify_cmd_label_in_verdict(self) -> None:
        bc = _make_mock_browser(
            snapshot_result="[页面] T\n[URL] http://localhost\n\nhero content visible"
        )
        prober = DomProber(bc)
        strategy = self._make_strategy(selector="hero")
        verdict = self._run_verdict(prober, strategy)
        assert verdict.verify_cmd is not None
        assert "hero" in verdict.verify_cmd or "dom_assert" in verdict.verify_cmd

    def test_detail_contains_rationale(self) -> None:
        bc = _make_mock_browser(
            snapshot_result="[页面] T\n[URL] http://localhost\n\ncontent"
        )
        prober = DomProber(bc)
        strategy = self._make_strategy()
        verdict = self._run_verdict(prober, strategy)
        assert "测试：检查元素存在" in verdict.detail, (
            f"verdict.detail 应含 rationale_human，实际: {verdict.detail!r}"
        )


# ═══════════════════════════════════════════════════════
# ═══════════════════════════════════════════════════════

class TestProposeDomVerifyParsing:

    def _make_loop_with_prober(self, browser=None):
        prober = DomProber(browser=browser)
        return _make_loop(dom_prober=prober)

    def test_valid_url_registers_l3_strategy(self) -> None:
        loop = self._make_loop_with_prober()
        ok = loop._on_propose_dom_verify(
            "url='http://localhost:3000', selector='h1', expected_text='Hello'"
        )
        assert ok is True
        assert loop._pending_l3_strategy is not None
        assert loop._pending_l3_strategy.level == "L3"

    def test_valid_https_url_accepted(self) -> None:
        loop = self._make_loop_with_prober()
        ok = loop._on_propose_dom_verify(
            "url='https://example.com', selector='.hero', expected_text='Welcome'"
        )
        assert ok is True
        assert loop._pending_l3_strategy is not None

    def test_file_url_rejected(self) -> None:
        loop = self._make_loop_with_prober()
        ok = loop._on_propose_dom_verify("url='file:///etc/passwd', selector='body'")
        assert ok is False
        assert loop._pending_l3_strategy is None

    def test_no_url_rejected(self) -> None:
        loop = self._make_loop_with_prober()
        ok = loop._on_propose_dom_verify("selector='h1', expected_text='hello'")
        assert ok is False
        assert loop._pending_l3_strategy is None

    def test_oversized_selector_rejected(self) -> None:
        loop = self._make_loop_with_prober()
        big_sel = "." + "x" * 501
        ok = loop._on_propose_dom_verify(
            f"url='http://localhost', selector='{big_sel}'"
        )
        assert ok is False
        assert loop._pending_l3_strategy is None

    def test_oversized_expected_text_rejected(self) -> None:
        loop = self._make_loop_with_prober()
        big_text = "x" * 501
        ok = loop._on_propose_dom_verify(
            f"url='http://localhost', expected_text='{big_text}'"
        )
        assert ok is False

    def test_no_dom_prober_returns_false(self) -> None:
        loop = _make_loop(dom_prober=None)
        ok = loop._on_propose_dom_verify(
            "url='http://localhost', selector='h1', expected_text='Hello'"
        )
        assert ok is False
        assert loop._pending_l3_strategy is None

    def test_explicit_verify_cmd_not_overridden(self) -> None:
        loop = _make_loop(dom_prober=DomProber(browser=None), verify_cmd="pytest")
        ok = loop._on_propose_dom_verify(
            "url='http://localhost', selector='h1', expected_text='Hello'"
        )
        assert ok is False
        assert loop._pending_l3_strategy is None

    def test_pending_dom_expected_text_stored(self) -> None:
        loop = self._make_loop_with_prober()
        loop._on_propose_dom_verify(
            "url='http://localhost', selector='h1', expected_text='My expected text'"
        )
        assert loop._pending_dom_expected_text == "My expected text"

    def test_no_expected_text_pending_field_empty(self) -> None:
        loop = self._make_loop_with_prober()
        loop._on_propose_dom_verify("url='http://localhost', selector='h1'")
        assert loop._pending_dom_expected_text == ""

    def test_reset_clears_pending_fields(self) -> None:
        loop = self._make_loop_with_prober()
        loop._pending_l3_strategy = object()
        loop._pending_dom_expected_text = "some text"
        loop._reset_run_state()
        assert loop._pending_l3_strategy is None
        assert loop._pending_dom_expected_text == ""

    def test_sandbox_stub_returns_receipt(self) -> None:
        from argos.tools import _propose_dom_verify_pure
        result = _propose_dom_verify_pure(
            url="http://localhost:3000",
            selector=".hero",
            expected_text="Welcome",
        )
        assert isinstance(result, str)
        assert len(result) > 0
        assert "localhost:3000" in result

    def test_sandbox_stub_with_defaults(self) -> None:
        from argos.tools import _propose_dom_verify_pure
        result = _propose_dom_verify_pure(url="http://example.com")
        assert isinstance(result, str)
        assert "example.com" in result

    def test_propose_dom_verify_in_all_tool_names(self) -> None:
        from argos.tools import ALL_TOOL_NAMES
        assert "propose_dom_verify" in ALL_TOOL_NAMES

    def test_propose_dom_verify_in_namespace(self) -> None:
        from argos.tools import _propose_dom_verify_pure
        import argos.tools as _t
        ns = _t._pure()
        assert "propose_dom_verify" in ns
        assert ns["propose_dom_verify"] is _propose_dom_verify_pure
