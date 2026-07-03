"""Internal documentation."""
from __future__ import annotations

import os
import queue
import threading
from dataclasses import dataclass
from typing import Any

from argos.i18n import t

_SNAPSHOT_MAX_CHARS = 4000
_NAV_TIMEOUT_MS = 20000
_ACTION_TIMEOUT_MS = 10000


@dataclass(frozen=True, slots=True)
class _Cmd:
    op: str
    args: dict[str, Any]


class BrowserController:
    """Internal documentation."""

    def __init__(self, *, headless: bool | None = None) -> None:
        if headless is None:
            headless = os.environ.get("ARGOS_BROWSER_HEADLESS", "") == "1"
        self._headless = headless
        self._cmd_q: "queue.Queue[_Cmd | None]" = queue.Queue()
        self._res_q: "queue.Queue[str]" = queue.Queue()
        self._thread: threading.Thread | None = None
        self._started = False
        self._lock = threading.Lock()
        self._launch_error: str | None = None

    def navigate(self, url: str) -> str:
        return self._call("navigate", {"url": url})

    def snapshot(self, max_chars: int = _SNAPSHOT_MAX_CHARS) -> str:
        return self._call("snapshot", {"max_chars": max_chars})

    def click(self, selector: str) -> str:
        return self._call("click", {"selector": selector})

    def type_text(self, selector: str, text: str) -> str:
        return self._call("type_text", {"selector": selector, "text": text})

    def screenshot(self, path: str) -> str:
        return self._call("screenshot", {"path": path})

    def close(self) -> None:
        with self._lock:
            if not self._started or self._thread is None:
                return
            self._cmd_q.put(None)
            self._thread.join(timeout=5.0)
            self._started = False
            self._thread = None

    def _ensure_started(self) -> str | None:
        """Internal documentation."""
        with self._lock:
            if self._started:
                return self._launch_error
            self._thread = threading.Thread(target=self._run, name="argos-browser", daemon=True)
            self._thread.start()
            self._started = True
        first = self._res_q.get()
        if first.startswith("__READY__"):
            self._launch_error = None
            return None
        self._launch_error = first
        return first

    def _call(self, op: str, args: dict[str, Any]) -> str:
        err = self._ensure_started()
        if err is not None:
            return err
        self._cmd_q.put(_Cmd(op=op, args=args))
        return self._res_q.get()

    def _run(self) -> None:
        """Internal documentation."""
        try:
            from playwright.sync_api import sync_playwright
        except Exception as e:  # noqa: BLE001
            self._res_q.put(t("browser.playwright_not_installed", exc=e))
            return
        try:
            with sync_playwright() as p:
                try:
                    browser = p.chromium.launch(
                        headless=self._headless,
                        args=["--disable-blink-features=AutomationControlled"],
                    )
                except Exception as e:  # noqa: BLE001
                    self._res_q.put(t("browser.launch_failed", exc=e))
                    return
                page = browser.new_page()
                self._res_q.put("__READY__")
                while True:
                    cmd = self._cmd_q.get()
                    if cmd is None:
                        break
                    self._res_q.put(self._dispatch(cmd, page))
                browser.close()
        except Exception as e:  # noqa: BLE001
            self._res_q.put(t("browser.thread_crashed", exc_type=type(e).__name__, exc=e))

    @staticmethod
    def _dispatch(cmd: _Cmd, page: Any) -> str:
        op, a = cmd.op, cmd.args
        try:
            if op == "navigate":
                page.goto(a["url"], timeout=_NAV_TIMEOUT_MS, wait_until="domcontentloaded")
                return t("browser.navigate_ok", url=a["url"], title=page.title())
            if op == "snapshot":
                title = page.title()
                url = page.url
                try:
                    body = page.inner_text("body", timeout=_ACTION_TIMEOUT_MS)
                except Exception:  # noqa: BLE001
                    body = ""
                mc = int(a.get("max_chars", _SNAPSHOT_MAX_CHARS))
                if len(body) > mc:
                    total_chars = len(body)
                    body = body[:mc] + t("browser.snapshot_truncated", total=total_chars, mc=mc)
                return t("browser.snapshot_header", title=title, url=url, body=body)
            if op == "click":
                page.click(a["selector"], timeout=_ACTION_TIMEOUT_MS)
                return t("browser.click_ok", selector=a["selector"])
            if op == "type_text":
                page.fill(a["selector"], a["text"], timeout=_ACTION_TIMEOUT_MS)
                return t("browser.type_ok", selector=a["selector"], chars=len(a["text"]))
            if op == "screenshot":
                page.screenshot(path=a["path"])
                return t("browser.screenshot_ok", path=a["path"])
            return t("browser.unknown_action", op=op)
        except Exception as e:  # noqa: BLE001
            return t("browser.action_failed", op=op, exc_type=type(e).__name__, exc=e)


_CONTROLLER: BrowserController | None = None
_CONTROLLER_LOCK = threading.Lock()


def get_controller() -> BrowserController:
    global _CONTROLLER
    with _CONTROLLER_LOCK:
        if _CONTROLLER is None:
            _CONTROLLER = BrowserController()
        return _CONTROLLER


def shutdown() -> None:
    """Internal documentation."""
    global _CONTROLLER
    with _CONTROLLER_LOCK:
        if _CONTROLLER is not None:
            _CONTROLLER.close()
            _CONTROLLER = None


import atexit as _atexit

_atexit.register(shutdown)
