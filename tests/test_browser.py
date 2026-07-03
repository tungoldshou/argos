"""Internal documentation."""
from __future__ import annotations

import pytest

from argos import browser as bmod
from argos.browser import BrowserController, _Cmd


class FakePage:
    """Internal documentation."""
    def __init__(self, *, title="Example", url="https://example.com", body="hello world"):
        self._title = title
        self._url = url
        self._body = body
        self.calls: list[tuple] = []

    def goto(self, url, **kw):
        self.calls.append(("goto", url))
        self._url = url

    def title(self):
        return self._title

    @property
    def url(self):
        return self._url

    def inner_text(self, selector, **kw):
        self.calls.append(("inner_text", selector))
        return self._body

    def click(self, selector, **kw):
        self.calls.append(("click", selector))

    def fill(self, selector, text, **kw):
        self.calls.append(("fill", selector, text))

    def screenshot(self, **kw):
        self.calls.append(("screenshot", kw.get("path")))


def test_dispatch_navigate():
    page = FakePage(title="Argos")
    out = BrowserController._dispatch(_Cmd("navigate", {"url": "https://a.com"}), page)
    assert "已打开 https://a.com" in out and "Argos" in out
    assert ("goto", "https://a.com") in page.calls


def test_dispatch_snapshot_truncates():
    page = FakePage(title="T", url="https://u.com", body="x" * 5000)
    out = BrowserController._dispatch(_Cmd("snapshot", {"max_chars": 100}), page)
    assert "[页面] T" in out and "[URL] https://u.com" in out
    assert "已截断前 100" in out


def test_dispatch_click_and_type():
    page = FakePage()
    assert "已点击" in BrowserController._dispatch(_Cmd("click", {"selector": "#btn"}), page)
    assert ("click", "#btn") in page.calls
    out = BrowserController._dispatch(_Cmd("type_text", {"selector": "#in", "text": "hi"}), page)
    assert "已在" in out and ("fill", "#in", "hi") in page.calls


def test_dispatch_screenshot():
    page = FakePage()
    out = BrowserController._dispatch(_Cmd("screenshot", {"path": "/tmp/a.png"}), page)
    assert "/tmp/a.png" in out and ("screenshot", "/tmp/a.png") in page.calls


def test_dispatch_unknown_action():
    assert "未知浏览器动作" in BrowserController._dispatch(_Cmd("fly", {}), FakePage())


def test_dispatch_page_error_is_honest_string():
    class BoomPage(FakePage):
        def goto(self, url, **kw):
            raise RuntimeError("net down")
    out = BrowserController._dispatch(_Cmd("navigate", {"url": "https://a.com"}), BoomPage())
    assert out.startswith("错误:浏览器动作 navigate 失败") and "net down" in out


def test_controller_threaded_call_with_fake_page(monkeypatch):
    """Internal documentation."""
    ctrl = BrowserController()
    page = FakePage(title="Z")

    def fake_run(self):
        self._res_q.put("__READY__")
        while True:
            cmd = self._cmd_q.get()
            if cmd is None:
                break
            self._res_q.put(self._dispatch(cmd, page))

    monkeypatch.setattr(BrowserController, "_run", fake_run)
    try:
        out = ctrl.navigate("https://z.com")
        assert "已打开 https://z.com" in out and "Z" in out
        snap = ctrl.snapshot()
        assert "[页面] Z" in snap
    finally:
        ctrl.close()


def test_controller_launch_failure_is_honest(monkeypatch):
    """Internal documentation."""
    ctrl = BrowserController()

    def boom_run(self):
        self._res_q.put("错误:浏览器启动失败(可能未安装 chromium)。请运行 `playwright install chromium` 后重试。")

    monkeypatch.setattr(BrowserController, "_run", boom_run)
    out = ctrl.navigate("https://a.com")
    assert out.startswith("错误:浏览器启动失败")
    assert ctrl.snapshot().startswith("错误:浏览器")


def test_broker_execute_routes_browser_actions(monkeypatch):
    from argos.sandbox.broker import CapabilityBroker, _RISK

    captured = []

    class FakeCtrl:
        def navigate(self, url):
            captured.append(("navigate", url)); return "NAV ok"
        def snapshot(self, mc):
            captured.append(("snapshot", mc)); return "SNAP ok"
        def click(self, s):
            captured.append(("click", s)); return "CLICK ok"
        def type_text(self, s, t):
            captured.append(("type", s, t)); return "TYPE ok"
        def screenshot(self, p):
            captured.append(("shot", p)); return "SHOT ok"

    monkeypatch.setattr("argos.browser.get_controller", lambda: FakeCtrl())

    broker = object.__new__(CapabilityBroker)
    broker._mcp_manager = None
    broker._browser_controller = None
    assert broker._execute("browser_navigate", {"url": "https://x.com"})[0] == "NAV ok"
    assert broker._execute("browser_snapshot", {"max_chars": 50})[0] == "SNAP ok"
    assert broker._execute("browser_click", {"selector": "#b"})[0] == "CLICK ok"
    assert broker._execute("browser_type", {"selector": "#i", "text": "hi"})[0] == "TYPE ok"
    assert broker._execute("browser_screenshot", {"path": "a.png"})[0] == "SHOT ok"
    assert captured[0] == ("navigate", "https://x.com")
    for a in ("browser_navigate", "browser_snapshot", "browser_click",
              "browser_type", "browser_screenshot"):
        assert a in _RISK


def test_browser_navigate_is_gated_and_ssrf_checked():
    """Internal documentation."""
    from argos.sandbox.broker import _NETWORK_ACTIONS, _RISK
    assert "browser_navigate" in _RISK
    assert "browser_navigate" in _NETWORK_ACTIONS
