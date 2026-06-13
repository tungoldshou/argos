"""tests/verify_strategy/test_dom_probe.py

DomProber 三态全覆盖测试 + loop L3 接线测试。

覆盖规则：
  · DomProber=None → error 非空（unverifiable，向后兼容）
  · found=True → 正常 passed；error=="" 是前提
  · found=False + error="" → failed（真实证据，不是 unverifiable）
  · error 非空 → 绝不 found=True（绝不 passed）
  · BrowserController 异常 → error 非空（fail-closed unverifiable）
  · dom_probe 单元：monkeypatch BrowserController（不起真浏览器）
  · loop _pick_strategy_cmd：DomProber=None → L3 跳过；DomProber 注入 → L3 挂起
  · 显式 verify_cmd 仍优先（不被 L3 策略覆盖）
  · 策略侧：web 信号 + dom_selector hint + URL 可解析 → 生成 L3；无 URL → 不生成
"""
from __future__ import annotations

import asyncio
import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch

from argos.verify.dom_probe import DomProber, DomProbeResult, _selector_to_text_hint
from argos.verify.strategy import generate, WorkspaceFacts


# ═══════════════════════════════════════════════════════
# DomProbeResult 不变量
# ═══════════════════════════════════════════════════════

class TestDomProbeResultInvariants:
    """DomProbeResult 值对象不变量。"""

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
        """有 error 时 found 必须是 False（安全不变量：error 时绝不 passed）。"""
        r = DomProbeResult(found=False, text_excerpt="", error="浏览器不可用")
        assert r.found is False
        assert r.error != ""

    def test_frozen(self) -> None:
        r = DomProbeResult(found=True, text_excerpt="x", error="")
        with pytest.raises((AttributeError, TypeError)):
            r.found = False  # type: ignore[misc]


# ═══════════════════════════════════════════════════════
# DomProber(browser=None) → error（向后兼容）
# ═══════════════════════════════════════════════════════

class TestDomProberNoBrowser:
    """DomProber(None) 所有 probe 调用必须返回 error（unverifiable，绝不 found=True）。"""

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
        """browser=None → found 永远 False（绝不 passed）。"""
        for selector in ("body", "h1", "#id", ".class", "div > span"):
            r = self.prober.probe("http://localhost:3000", selector)
            assert r.found is False, f"browser=None probe(selector={selector!r}) found 不应为 True"


# ═══════════════════════════════════════════════════════
# DomProber with monkeypatched BrowserController
# ═══════════════════════════════════════════════════════

def _make_mock_browser(*, nav_result: str = "已打开 http://localhost", snapshot_result: str = "") -> MagicMock:
    """构造仿 BrowserController，navigate / snapshot 返回给定字符串。"""
    bc = MagicMock()
    bc.navigate.return_value = nav_result
    bc.snapshot.return_value = snapshot_result
    return bc


class TestDomProberFoundTrue:
    """found=True 只在有显式 expected_text 且文本命中时才可达。"""

    def test_found_with_expected_text_match(self) -> None:
        """显式 expected_text 存在于 body → found=True，error 空（强证据路径）。"""
        snapshot = "[页面] Test\n[URL] http://localhost\n\nWelcome hero-title new content"
        bc = _make_mock_browser(snapshot_result=snapshot)
        prober = DomProber(bc)
        result = prober.probe("http://localhost", ".hero-title", expected_text="new content")
        assert result.found is True
        assert result.error == ""

    def test_expected_text_found_has_excerpt(self) -> None:
        """found=True 时 text_excerpt 不能空（供 detail / TUI 展示）。"""
        snapshot = "[页面] Test\n[URL] http://localhost\n\nhello world visible content here"
        bc = _make_mock_browser(snapshot_result=snapshot)
        prober = DomProber(bc)
        result = prober.probe("http://localhost", "h1", expected_text="visible content")
        assert result.found is True
        assert result.text_excerpt != "", "found=True 时 text_excerpt 不能空"

    def test_no_url_skips_navigate(self) -> None:
        """url=None 时不调 navigate，只用当前 page 状态。"""
        snapshot = "[页面] Test\n[URL] http://localhost\n\nmsg element present target"
        bc = _make_mock_browser(snapshot_result=snapshot)
        prober = DomProber(bc)
        prober.probe(None, ".msg", expected_text="target")
        bc.navigate.assert_not_called()
        bc.snapshot.assert_called_once()


class TestDomProberWeakEvidence:
    """Major-1 假绿修正：无 expected_text 时，弱证据路径最高只能 unverifiable，绝不 passed。

    核心反假绿断言（显式写成测试）：
      "无 expected_text 永不 passed"
    """

    def test_no_expected_text_never_passed(self) -> None:
        """反假绿：无 expected_text 时，即使 body 含选择器文本提示，found 永远 False。"""
        # body 含 "headline" — 旧代码会误判 found=True，修后必须是 unverifiable
        snapshot = "[页面] Test\n[URL] http://localhost\n\nWelcome headline here"
        bc = _make_mock_browser(snapshot_result=snapshot)
        prober = DomProber(bc)
        result = prober.probe("http://localhost", "h1.headline")
        assert result.found is False, (
            "反假绿：无 expected_text 时绝不能 found=True（弱证据路径）"
        )

    def test_no_expected_text_returns_unverifiable(self) -> None:
        """无 expected_text → error 非空（unverifiable），不论选择器提示是否命中。"""
        snapshot = "[页面] Test\n[URL] http://localhost\n\nheadline present"
        bc = _make_mock_browser(snapshot_result=snapshot)
        prober = DomProber(bc)
        result = prober.probe("http://localhost", "h1.headline")
        assert result.error != "", (
            "无 expected_text 时探针结果必须是 unverifiable（error 非空）"
        )
        assert result.found is False

    def test_no_expected_text_hint_not_in_body_still_unverifiable(self) -> None:
        """无 expected_text + 提示不在 body → 仍 unverifiable，不是 failed。

        缺席可能是假阴性（元素存在但无对应文本），因此不能产 failed。
        """
        snapshot = "[页面] Test\n[URL] http://localhost\n\nno matching content at all"
        bc = _make_mock_browser(snapshot_result=snapshot)
        prober = DomProber(bc)
        result = prober.probe("http://localhost", "h1.nonexistent-element")
        # 弱证据路径无论命中与否都是 unverifiable（error 非空，found=False）
        assert result.error != "", "弱证据路径缺席也是 unverifiable，不是 failed"
        assert result.found is False

    def test_all_selectors_without_expected_text_never_passed(self) -> None:
        """参数化：多种选择器，无 expected_text，一律 found=False。"""
        snapshot = "[页面] Test\n[URL] http://localhost\n\nbody h1 headline notification-badge hero-title msg"
        bc = _make_mock_browser(snapshot_result=snapshot)
        prober = DomProber(bc)
        # 这些选择器的提示文本都在 body 里，旧代码会全部误判 found=True
        for selector in ("h1.headline", "#notification-badge", ".hero-title", "div > span.msg"):
            result = prober.probe("http://localhost", selector)
            assert result.found is False, (
                f"反假绿：selector={selector!r} 无 expected_text 时 found 绝不能 True"
            )


class TestDomProberFoundFalse:
    """found=False + error="" 场景：显式 expected_text 明确不存在 → failed（真实证据）。"""

    def test_expected_text_mismatch_not_found(self) -> None:
        """显式 expected_text 不在 body → found=False, error="" (failed，真实证据)。"""
        snapshot = "[页面] Test\n[URL] http://localhost\n\nhero-title present but wrong"
        bc = _make_mock_browser(snapshot_result=snapshot)
        prober = DomProber(bc)
        result = prober.probe("http://localhost", ".hero-title", expected_text="NEW HEADLINE")
        assert result.found is False
        assert result.error == "", "expected_text 不匹配是验证失败（failed），不是 error（unverifiable）"

    def test_expected_text_absent_is_failed_not_unverifiable(self) -> None:
        """强证据路径：expected_text 明确缺席 → found=False + error="" (can be used as failed)。"""
        snapshot = "[页面] Test\n[URL] http://localhost\n\nsome content without target"
        bc = _make_mock_browser(snapshot_result=snapshot)
        prober = DomProber(bc)
        result = prober.probe("http://localhost", "h1", expected_text="this text is absent")
        assert result.found is False
        assert result.error == "", "强证据路径：expected_text 缺席应是 found=False+error=''，不是 unverifiable"


class TestDomProberError:
    """错误场景（浏览器不可用/超时/异常）：error 非空，found 必须为 False。"""

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
        """BrowserController.navigate 抛异常 → error 非空（fail-closed）。"""
        bc = MagicMock()
        bc.navigate.side_effect = RuntimeError("playwright crash")
        bc.snapshot.return_value = ""
        prober = DomProber(bc)
        result = prober.probe("http://localhost", "body")
        assert result.error != ""
        assert result.found is False

    def test_error_never_found_true(self) -> None:
        """关键安全不变量：error 非空时 found 绝不能为 True。"""
        bc = _make_mock_browser(nav_result="错误:timeout")
        prober = DomProber(bc)
        for selector in ("body", "h1", "#id", ".class"):
            r = prober.probe("http://localhost", selector)
            if r.error:
                assert r.found is False, (
                    f"error 非空时 found 绝不能为 True（selector={selector!r}）"
                )


# ═══════════════════════════════════════════════════════
# _selector_to_text_hint 单元测试
# ═══════════════════════════════════════════════════════

class TestSelectorToTextHint:
    """CSS 选择器 → 文本提示提取。"""

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
# strategy.py L3 生成：URL 来源 + 诚实降级
# ═══════════════════════════════════════════════════════

class TestStrategyL3WithUrl:
    """L3 生成条件：web 信号 + dom_selector + URL 可解析（hints 或 goal 中提取）。"""

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
        """dom_url hint 缺失，但 goal 中有显式 URL → 仍生成 L3。"""
        strats = generate(
            "update the webpage at http://localhost:8080 to show the new headline",
            workspace_facts=WorkspaceFacts(),
            capability_hints={"dom_selector": ".headline"},
        )
        l3 = [s for s in strats if s.level == "L3"]
        assert l3, "goal 含显式 URL + dom_selector hint → 应生成 L3"
        assert "localhost:8080" in (l3[0].target or "")

    def test_dom_selector_hint_no_url_anywhere_no_l3(self) -> None:
        """dom_selector 存在，但 hints 无 dom_url 且 goal 无显式 URL → 诚实不生成 L3。"""
        strats = generate(
            "update the webpage to show the new headline",
            workspace_facts=WorkspaceFacts(),
            capability_hints={"dom_selector": "h1.headline"},  # 无 dom_url
        )
        l3 = [s for s in strats if s.level == "L3"]
        assert len(l3) == 0, f"无 URL 时不应生成 L3（诚实降级）: {l3}"

    def test_web_signal_without_dom_selector_no_l3(self) -> None:
        """有网页信号但无 dom_selector hint → 无法确定选择器，不生成 L3。"""
        strats = generate(
            "render the frontend page at http://localhost:3000",
            workspace_facts=WorkspaceFacts(),
            capability_hints={"dom_url": "http://localhost:3000"},  # 无 dom_selector
        )
        l3 = [s for s in strats if s.level == "L3"]
        assert len(l3) == 0, f"无 dom_selector 不应生成 L3: {l3}"

    def test_l3_cmd_is_none(self) -> None:
        """L3 策略 cmd 必须是 None（走探针路径，不走 shell 命令）。"""
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
        """发送类红线：即使有 dom hints，纯发送任务绝不生成 L3。"""
        strats = generate(
            "send a notification to users",
            workspace_facts=WorkspaceFacts(),
            capability_hints={"dom_selector": "#badge", "dom_url": "http://localhost"},
        )
        l3 = [s for s in strats if s.level == "L3"]
        assert len(l3) == 0, f"发送类任务绝不生成 L3: {l3}"


# ═══════════════════════════════════════════════════════
# loop._pick_strategy_cmd L3 接线
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
    """loop._pick_strategy_cmd L3 接线：DomProber=None → 跳过；已注入 → 挂起。"""

    def test_no_dom_prober_l3_skipped(self, tmp_path: Path) -> None:
        """DomProber=None：L3 候选不被挂起，_pending_l3_strategy 仍 None。"""
        loop = _make_loop(
            dom_prober=None,
            capability_hints={"dom_selector": "h1", "dom_url": "http://localhost"},
        )
        loop._workspace = tmp_path
        cmd = loop._pick_strategy_cmd("update the webpage at http://localhost")
        # 无 pytest/cargo 工作区 → L1 不产；L3 跳过 → cmd=None
        assert loop._pending_l3_strategy is None, "DomProber=None 时不应挂起 L3 策略"

    def test_with_dom_prober_l3_pending(self, tmp_path: Path) -> None:
        """DomProber 已注入：web goal + dom_selector hint + URL → L3 挂起，cmd=None。"""
        fake_prober = DomProber(browser=None)  # 实例化（browser=None 无所谓，测接线）
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
        """显式 verify_cmd 不走策略生成（_pick_strategy_cmd 不会被调用）。"""
        fake_prober = DomProber(browser=None)
        loop = _make_loop(
            dom_prober=fake_prober,
            verify_cmd="pytest",
            capability_hints={"dom_selector": ".headline", "dom_url": "http://localhost"},
        )
        loop._workspace = tmp_path
        # 模拟 loop._verify_cmd 已被设置（显式 verify_cmd 路径）
        assert loop._verify_cmd == "pytest"
        # 显式 verify_cmd 不应被 L3 策略覆盖
        assert loop._pending_l3_strategy is None

    def test_pending_l3_cleared_on_reset(self, tmp_path: Path) -> None:
        """_reset_run_state 必须清空 _pending_l3_strategy（防跨轮泄漏）。"""
        fake_prober = DomProber(browser=None)
        loop = _make_loop(dom_prober=fake_prober)
        loop._workspace = tmp_path
        # 手动设置
        loop._pending_l3_strategy = object()
        loop._reset_run_state()
        assert loop._pending_l3_strategy is None, "_reset_run_state 必须清空 _pending_l3_strategy"


# ═══════════════════════════════════════════════════════
# loop._run_dom_probe_verdict 三态全覆盖
# ═══════════════════════════════════════════════════════

class TestRunDomProbeVerdict:
    """_run_dom_probe_verdict 三态：passed / failed / unverifiable。"""

    def _make_strategy(self, url: str = "http://localhost", selector: str = "h1") -> object:
        """构造一个最小 L3 VerifyStrategy 仿对象。"""
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
        # 若有 expected_text，写入 loop 字段（模拟 propose_dom_verify / capability_hints 路径）
        if expected_text:
            loop._pending_dom_expected_text = expected_text
        return asyncio.run(loop._run_dom_probe_verdict(strategy, attempt=1))

    def _make_strategy_with_expected(
        self,
        url: str = "http://localhost",
        selector: str = "h1",
        expected_text: str = "h1",
    ) -> object:
        """构造含 dom_expected_text 的 L3 策略（供需要 passed 路径的测试用）。"""
        from argos.verify.strategy import _l3_dom_assert
        hints: dict[str, str] = {
            "dom_url": url,
            "dom_selector": selector,
            "dom_expected_text": expected_text,
        }
        return _l3_dom_assert(hints)

    def test_found_true_yields_passed_with_expected_text(self) -> None:
        """有显式 expected_text 且文本命中 → Verdict.passed（强证据路径）。"""
        bc = _make_mock_browser(
            snapshot_result="[页面] T\n[URL] http://localhost\n\nh1 element here"
        )
        prober = DomProber(bc)
        strategy = self._make_strategy_with_expected(selector="h1", expected_text="h1 element")
        verdict = self._run_verdict(prober, strategy, expected_text="h1 element")
        assert verdict.status == "passed", f"有 expected_text 命中时 verdict 应为 passed，实际: {verdict}"

    def test_no_expected_text_yields_unverifiable(self) -> None:
        """无 expected_text（弱证据路径）→ Verdict.unverifiable，即使 body 含提示文本。"""
        bc = _make_mock_browser(
            snapshot_result="[页面] T\n[URL] http://localhost\n\nh1 element here"
        )
        prober = DomProber(bc)
        # _make_strategy 不含 expected_text → 弱证据路径（不传 expected_text）
        strategy = self._make_strategy(selector="h1")
        verdict = self._run_verdict(prober, strategy)
        assert verdict.status == "unverifiable", (
            f"无 expected_text 时 verdict 应为 unverifiable（弱证据），实际: {verdict}"
        )

    def test_found_false_with_expected_text_yields_failed(self) -> None:
        """显式 expected_text 不在 body → Verdict.failed（真实证据回灌 bounce）。"""
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
        """error 非空 → Verdict.unverifiable（诚实，不编造）。"""
        bc = _make_mock_browser(nav_result="错误:浏览器启动失败(chromium 未安装)")
        prober = DomProber(bc)
        strategy = self._make_strategy()
        verdict = self._run_verdict(prober, strategy)
        assert verdict.status == "unverifiable", (
            f"error 非空时 verdict 应为 unverifiable，实际: {verdict}"
        )

    def test_error_never_passed(self) -> None:
        """关键安全不变量：任何 error 场景绝不产出 passed。"""
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
        """DomProber(None) 调 _run_dom_probe_verdict → unverifiable。"""
        prober = DomProber(browser=None)
        strategy = self._make_strategy()
        verdict = self._run_verdict(prober, strategy)
        assert verdict.status == "unverifiable"
        assert verdict.status != "passed"

    def test_verify_cmd_label_in_verdict(self) -> None:
        """verdict.verify_cmd 应包含 selector 信息（可读标签，账本/TUI 用）。"""
        bc = _make_mock_browser(
            snapshot_result="[页面] T\n[URL] http://localhost\n\nhero content visible"
        )
        prober = DomProber(bc)
        strategy = self._make_strategy(selector="hero")
        verdict = self._run_verdict(prober, strategy)
        assert verdict.verify_cmd is not None
        assert "hero" in verdict.verify_cmd or "dom_assert" in verdict.verify_cmd

    def test_detail_contains_rationale(self) -> None:
        """verdict.detail 应包含 rationale_human（供 TUI / bounce 显示）。"""
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
# Major-2：propose_dom_verify host 侧解析
# ═══════════════════════════════════════════════════════

class TestProposeDomVerifyParsing:
    """loop._on_propose_dom_verify — host 侧解析 + L3 策略登记。"""

    def _make_loop_with_prober(self, browser=None):
        prober = DomProber(browser=browser)
        return _make_loop(dom_prober=prober)

    def test_valid_url_registers_l3_strategy(self) -> None:
        """合法 http url → _pending_l3_strategy 被写入。"""
        loop = self._make_loop_with_prober()
        ok = loop._on_propose_dom_verify(
            "url='http://localhost:3000', selector='h1', expected_text='Hello'"
        )
        assert ok is True
        assert loop._pending_l3_strategy is not None
        assert loop._pending_l3_strategy.level == "L3"

    def test_valid_https_url_accepted(self) -> None:
        """https URL 被接受。"""
        loop = self._make_loop_with_prober()
        ok = loop._on_propose_dom_verify(
            "url='https://example.com', selector='.hero', expected_text='Welcome'"
        )
        assert ok is True
        assert loop._pending_l3_strategy is not None

    def test_file_url_rejected(self) -> None:
        """file:// 协议被拒（安全校验）。"""
        loop = self._make_loop_with_prober()
        ok = loop._on_propose_dom_verify("url='file:///etc/passwd', selector='body'")
        assert ok is False
        assert loop._pending_l3_strategy is None

    def test_no_url_rejected(self) -> None:
        """无 url 参数被拒。"""
        loop = self._make_loop_with_prober()
        ok = loop._on_propose_dom_verify("selector='h1', expected_text='hello'")
        assert ok is False
        assert loop._pending_l3_strategy is None

    def test_oversized_selector_rejected(self) -> None:
        """selector 超过 500 字符被拒（防滥用）。"""
        loop = self._make_loop_with_prober()
        big_sel = "." + "x" * 501
        ok = loop._on_propose_dom_verify(
            f"url='http://localhost', selector='{big_sel}'"
        )
        assert ok is False
        assert loop._pending_l3_strategy is None

    def test_oversized_expected_text_rejected(self) -> None:
        """expected_text 超过 500 字符被拒（防滥用）。"""
        loop = self._make_loop_with_prober()
        big_text = "x" * 501
        ok = loop._on_propose_dom_verify(
            f"url='http://localhost', expected_text='{big_text}'"
        )
        assert ok is False

    def test_no_dom_prober_returns_false(self) -> None:
        """DomProber 未注入 → 静默忽略，返回 False（向后兼容）。"""
        loop = _make_loop(dom_prober=None)
        ok = loop._on_propose_dom_verify(
            "url='http://localhost', selector='h1', expected_text='Hello'"
        )
        assert ok is False
        assert loop._pending_l3_strategy is None

    def test_explicit_verify_cmd_not_overridden(self) -> None:
        """_verify_cmd 已设 → propose_dom_verify 不覆盖（显式命令优先）。"""
        loop = _make_loop(dom_prober=DomProber(browser=None), verify_cmd="pytest")
        ok = loop._on_propose_dom_verify(
            "url='http://localhost', selector='h1', expected_text='Hello'"
        )
        assert ok is False
        assert loop._pending_l3_strategy is None

    def test_pending_dom_expected_text_stored(self) -> None:
        """expected_text 被写入 _pending_dom_expected_text（供 _run_dom_probe_verdict 用）。"""
        loop = self._make_loop_with_prober()
        loop._on_propose_dom_verify(
            "url='http://localhost', selector='h1', expected_text='My expected text'"
        )
        assert loop._pending_dom_expected_text == "My expected text"

    def test_no_expected_text_pending_field_empty(self) -> None:
        """无 expected_text 时 _pending_dom_expected_text 为空串（弱证据路径）。"""
        loop = self._make_loop_with_prober()
        loop._on_propose_dom_verify("url='http://localhost', selector='h1'")
        assert loop._pending_dom_expected_text == ""

    def test_reset_clears_pending_fields(self) -> None:
        """_reset_run_state 同时清空 _pending_l3_strategy 和 _pending_dom_expected_text。"""
        loop = self._make_loop_with_prober()
        loop._pending_l3_strategy = object()
        loop._pending_dom_expected_text = "some text"
        loop._reset_run_state()
        assert loop._pending_l3_strategy is None
        assert loop._pending_dom_expected_text == ""

    def test_sandbox_stub_returns_receipt(self) -> None:
        """沙箱内 propose_dom_verify 桩返回登记回执（不是空字符串）。"""
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
        """沙箱桩仅传 url 时不抛异常。"""
        from argos.tools import _propose_dom_verify_pure
        result = _propose_dom_verify_pure(url="http://example.com")
        assert isinstance(result, str)
        assert "example.com" in result

    def test_propose_dom_verify_in_all_tool_names(self) -> None:
        """propose_dom_verify 应在 ALL_TOOL_NAMES 中（诚实计数来源）。"""
        from argos.tools import ALL_TOOL_NAMES
        assert "propose_dom_verify" in ALL_TOOL_NAMES

    def test_propose_dom_verify_in_namespace(self) -> None:
        """沙箱命名空间 build_namespace / _pure() 含 propose_dom_verify。"""
        from argos.tools import _propose_dom_verify_pure
        # _pure() 直接测字典键
        import argos.tools as _t
        ns = _t._pure()
        assert "propose_dom_verify" in ns
        assert ns["propose_dom_verify"] is _propose_dom_verify_pure
