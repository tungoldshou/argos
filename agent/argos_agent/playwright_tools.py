"""电脑操控工具(第 7 步)—— Playwright Python SDK 包成 LangChain tool。

设计:单 browser / 单 context(lazy init,首次 invoke 才拉起),并发 run 同用会冲突(spec §2 红线);
navigate 改地址+cookies+状态=走审批闸;snapshot 只读=不走;click/type_text 写操作=走审批闸。

不依赖 MCP:spec 探针已证 chrome-devtools MCP 时序不稳(list_pages 报 about:blank),
Playwright Python SDK 同步阻塞+HTTP 状态码做凭据,实证稳(pw_probe.py)。

审批门接法:与 run_command 同款 —— @requires_approval 装饰裸函数,@tool 再包 wrapper,
StructuredTool.coroutine = 审批 wrapper,invoke 真拦 gate。
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any

from langchain_core.tools import ToolException, tool

from . import approval

log = logging.getLogger(__name__)

# 单 browser / 单 context / 单 page(单 run 用;并发 run 同用会有冲突,在工具描述里明示)
_BROWSER: Any = None
_CONTEXT: Any = None
_PAGE: Any = None
_BROWSER_LOCK: asyncio.Lock | None = None
# 启动时 toggle(False)=整步降级为只读探查类工具(见 spec §6 降级路径)
ENABLED_WRITE_TOOLS: bool = True


def _reset_for_test() -> None:
    """测试 hook:重置全局单例。生产路径不应调。"""
    global _BROWSER, _CONTEXT, _PAGE
    _BROWSER = _CONTEXT = _PAGE = None


def _set_browser_for_test(page: Any) -> None:
    """测试 hook:直接注入 mock page 到全局。生产路径不应调。
    等价于跑过 _ensure_browser 一次(launch+context+new_page),直接给结果。
    """
    global _BROWSER, _CONTEXT, _PAGE
    _BROWSER = None
    _CONTEXT = None
    _PAGE = page


async def _ensure_browser() -> Any:
    """Lazy init 单 browser / context / page。失败抛 ToolException("browser unavailable: ...")。"""
    global _BROWSER, _CONTEXT, _PAGE, _BROWSER_LOCK
    if _PAGE is not None:
        return _PAGE
    if _BROWSER_LOCK is None:
        _BROWSER_LOCK = asyncio.Lock()
    async with _BROWSER_LOCK:
        if _PAGE is not None:
            return _PAGE
        try:
            from playwright.async_api import async_playwright
            pw = await async_playwright().start()
            _BROWSER = await pw.chromium.launch(headless=True)
            _CONTEXT = await _BROWSER.new_context()
            _PAGE = await _CONTEXT.new_page()
            return _PAGE
        except Exception as e:
            raise ToolException(f"browser unavailable: {e!r}")


# ── 4 件 LangChain tool(双装饰同 run_command) ──────────────────────────
# 顺序:@requires_approval 装饰裸函数 → @tool 再包 → StructuredTool.coroutine = 审批 wrapper
#       → invoke 真拦 gate(functools.wraps 保留原 __name__,@tool 据此建 StructuredTool.name)。
# snapshot 不走审批,只 @tool。
# 注:@tool decorator 内部 inspect 签名时,@requires_approval 装饰的 wrapper.__wrapped__ 链能
# 透传回原 async def,args schema 才能正确(否则模型看到 (*args, **kwargs))。


@approval.requires_approval(description="打开浏览器到 {url}", risk="low")
async def navigate(url: str) -> dict:
    """打开 URL 到浏览器 page,等 DOMContentLoaded,返 title/url/loaded。

    副作用:改地址+cookies+状态,需走审批闸(产品决策,不是只读)。
    注意:本工具是单 run 单浏览器;并发 run 同用会有冲突。
    """
    try:
        page = await _ensure_browser()
        resp = await page.goto(url, wait_until="domcontentloaded", timeout=30000)
        return {"title": await page.title(), "url": page.url,
                "loaded": True, "status": getattr(resp, "status", None)}
    except Exception as e:
        if isinstance(e, ToolException):
            raise
        raise ToolException(f"navigate {url!r} failed: {e!r}")


navigate = tool(navigate)


@tool
async def snapshot() -> dict:
    """读当前 page 的 title / url / 主要 heading 文本。只读,不需要审批。

    返回 {title, url, headings: list[str]}。A11y 树在 Playwright Python 里未直接暴露,
    这里用 title + page.url + heading 元素(用通用选择器)拼出核心结构。
    """
    try:
        page = await _ensure_browser()
        title = await page.title()
        url = page.url
        headings: list[str] = []
        try:
            headings = await page.locator("h1, h2, h3").all_inner_texts()
        except Exception:
            pass
        return {"title": title, "url": url, "headings": headings[:10]}
    except Exception as e:
        if isinstance(e, ToolException):
            raise
        raise ToolException(f"snapshot failed: {e!r}")


@approval.requires_approval(description="点击页面元素 {selector}", risk="low")
async def click(selector: str) -> dict:
    """点击当前 page 上由 CSS selector 指定的元素。写操作,需审批。

    注意:selector 错了 / 元素不可点 → Playwright 抛 TimeoutError → 包 ToolException。
    """
    if not ENABLED_WRITE_TOOLS:
        raise ToolException("click disabled (降级为只读探查类工具;spec §6 降级路径)")
    try:
        page = await _ensure_browser()
        await page.click(selector, timeout=10000)
        return {"ok": True, "selector": selector, "url": page.url}
    except Exception as e:
        if isinstance(e, ToolException):
            raise
        raise ToolException(f"click {selector!r} failed: {e!r}")


click = tool(click)


@approval.requires_approval(description="在 {selector} 填入文本", risk="medium")
async def type_text(selector: str, text: str) -> dict:
    """在 selector 指定的输入框里填 text。写操作,需审批。"""
    if not ENABLED_WRITE_TOOLS:
        raise ToolException("type_text disabled (降级为只读探查类工具;spec §6 降级路径)")
    try:
        page = await _ensure_browser()
        await page.fill(selector, text, timeout=10000)
        return {"ok": True, "selector": selector, "text": text, "url": page.url}
    except Exception as e:
        if isinstance(e, ToolException):
            raise
        raise ToolException(f"type_text {selector!r} failed: {e!r}")


type_text = tool(type_text)


def all_tools() -> list:
    """返 4 件 tool(snapshot 只读直接用;navigate/click/type_text 走审批闸包装)。

    测试用 `_set_browser_for_test` 注入 mock;生产路径第一次 invoke 触发 lazy init。
    """
    return [navigate, snapshot, click, type_text]
