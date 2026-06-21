"""计算机控制(浏览器自动化)—— Argos 超能力之一,让 agent 在"写代码 + 联网检索"之外
还能真的开浏览器、导航、读页面、点按、填表。

为什么要一条专用线程:
  · Playwright 的 **sync API 不能跑在 asyncio 事件循环线程里**(会抛 "Sync API inside
    asyncio loop")。而 broker `_execute` 恰恰跑在 loop 线程上(`exec_code` 同步阻塞 loop)。
  · 解法:`BrowserController` 起一条**守护线程**,在其中独占一个 sync Playwright + 持久
    browser/page;`_execute` 只往命令队列投一条指令、阻塞等结果队列 —— 真正的 Playwright
    调用发生在 loop 线程之外,绕开冲突。loop 本就在 exec_code 期间同步阻塞,故"阻塞等队列"
    与现有行为一致,不引入新卡顿语义。

诚实(灵魂):
  · 懒启动 —— 第一次真用到才 launch chromium;没装 chromium / 启动失败 → **返回诚实错误串**
    (告诉 agent + 用户"浏览器不可用,请 `playwright install chromium`"),绝不假装点过。
  · 每个动作 try/except,失败返回可读错误(模型据此换路,不抛异常崩 run)。
  · 单例 + 进程退出时尽力关闭(close());不残留僵尸 chromium。
"""
from __future__ import annotations

import os
import queue
import threading
from dataclasses import dataclass
from typing import Any

from argos.i18n import t

# 页面正文截断上限(snapshot 回灌给模型的预算,防把整页塞爆上下文)。
_SNAPSHOT_MAX_CHARS = 4000
_NAV_TIMEOUT_MS = 20000
_ACTION_TIMEOUT_MS = 10000


@dataclass(frozen=True, slots=True)
class _Cmd:
    op: str
    args: dict[str, Any]


class BrowserController:
    """单线程持有 sync Playwright + 持久 page 的浏览器控制器。线程安全入口:host 侧调
    navigate/snapshot/click/type_text/screenshot,内部投命令队列、阻塞取结果。"""

    def __init__(self, *, headless: bool | None = None) -> None:
        # 默认【有头/可见】—— 计算机控制的本意就是让用户**看着** agent 开浏览器、点按、填表;
        # headless 模式不弹窗,用户会以为"没打开浏览器"。无显示器/CI/SSH 环境可 ARGOS_BROWSER_HEADLESS=1
        # 强制无头(此时 launch 仍能成功;有头在无显示器环境才会失败 → 诚实错误)。
        if headless is None:
            headless = os.environ.get("ARGOS_BROWSER_HEADLESS", "") == "1"
        self._headless = headless
        self._cmd_q: "queue.Queue[_Cmd | None]" = queue.Queue()
        self._res_q: "queue.Queue[str]" = queue.Queue()
        self._thread: threading.Thread | None = None
        self._started = False
        self._lock = threading.Lock()
        self._launch_error: str | None = None

    # ── host 侧公开 API(全部返回字符串:结果或诚实错误)─────────────────────────
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

    # ── 内部:懒启动线程 + 投命令/取结果 ────────────────────────────────────────
    def _ensure_started(self) -> str | None:
        """启动浏览器线程并等它就绪。返回 None=成功;非 None=诚实错误串(启动失败)。"""
        with self._lock:
            if self._started:
                return self._launch_error
            self._thread = threading.Thread(target=self._run, name="argos-browser", daemon=True)
            self._thread.start()
            self._started = True
        # 等线程发回 ready / 启动错误(第一条结果)。
        first = self._res_q.get()
        if first.startswith("__READY__"):
            self._launch_error = None
            return None
        self._launch_error = first  # 启动失败原因(诚实回传)
        return first

    def _call(self, op: str, args: dict[str, Any]) -> str:
        err = self._ensure_started()
        if err is not None:
            return err
        self._cmd_q.put(_Cmd(op=op, args=args))
        return self._res_q.get()

    def _run(self) -> None:
        """浏览器线程主体:独占 sync Playwright + 持久 page,循环处理命令。"""
        try:
            from playwright.sync_api import sync_playwright
        except Exception as e:  # noqa: BLE001
            self._res_q.put(t("browser.playwright_not_installed", exc=e))
            return
        try:
            with sync_playwright() as p:
                try:
                    # --disable-blink-features=AutomationControlled:去掉 navigator.webdriver
                    # 自动化指纹,让真实站点(尤其 Google)少一点直接弹反机器人验证。诚实:这不
                    # 保证绕过 CAPTCHA —— 大站仍可能挑战自动化;命中时 agent 会如实换路(web_search)。
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
        except Exception as e:  # noqa: BLE001 — 线程级兜底,绝不让浏览器线程静默死掉
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
        except Exception as e:  # noqa: BLE001 — 单动作失败返回可读错误,模型据此换路
            return t("browser.action_failed", op=op, exc_type=type(e).__name__, exc=e)


# ── 进程内单例(broker._execute 通过 get_controller() 取用)──────────────────────
_CONTROLLER: BrowserController | None = None
_CONTROLLER_LOCK = threading.Lock()


def get_controller() -> BrowserController:
    global _CONTROLLER
    with _CONTROLLER_LOCK:
        if _CONTROLLER is None:
            _CONTROLLER = BrowserController()
        return _CONTROLLER


def shutdown() -> None:
    """进程退出 / 测试清理:关闭单例浏览器(若已启动)。"""
    global _CONTROLLER
    with _CONTROLLER_LOCK:
        if _CONTROLLER is not None:
            _CONTROLLER.close()
            _CONTROLLER = None


# 进程正常退出时收掉单例浏览器(不残留 chromium 子进程)。daemon 线程在硬退出时会被杀,
# atexit 覆盖正常退出路径(import browser 已是"真用到浏览器"的信号,此时注册无副作用)。
import atexit as _atexit

_atexit.register(shutdown)
