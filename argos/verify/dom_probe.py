"""argos/verify/dom_probe.py —— DOM 断言探针（验证梯子 L3）。

host 侧只读验证器件：给定 URL + CSS 选择器，通过 BrowserController 确认该元素
存在且（可选）包含期望文本。**绝不被 agent 代码控制**——探针在 host 侧 verify 阶段
调用，agent 的沙箱代码无法影响其结果。

三态承诺（诚实不变量）：
  · found=True, error="" → 声明的 expected_text 完整出现在 body 文本 → passed
      （仅在显式传入 expected_text 时可达 passed；纯选择器派生的文本提示绝不 passed）
  · found=False, error="" → expected_text 明确不出现 → failed（真实证据）
  · found=False, error非空 → 浏览器不可用/超时/异常/仅有模糊提示 → unverifiable（诚实降级）

证据强度分级（Major-1 修正）：
  · 有显式 expected_text（声明式内容断言）→ 强证据，可产 passed / failed。
  · 无 expected_text，只有选择器派生的文本提示 → 弱证据，最高只能 unverifiable，
    绝不产 passed（提示是启发式提取，命中≠元素真实存在，缺席也可能是假阴性）。
  · probe error → unverifiable（现行为保留）。

设计约束：
  · 只用 BrowserController 已有的 navigate / snapshot 公开 API，走最小路径；
    不依赖任何 playwright 内部 API，不引入新依赖。
  · BrowserController=None → 未接入，probe 直接返回 error（向后兼容：行为同现状
    _pick_strategy_cmd 跳过 L3）。
  · 超时由 BrowserController._call 内部处理（Playwright timeout）；此层不再套
    asyncio.timeout（probe 在同步 loop._pick_strategy_cmd 内被调用）。
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from argos.i18n import is_error_result, t

if TYPE_CHECKING:
    from argos.browser import BrowserController

# navigate 后等页面稳定用的内置超时已在 BrowserController _NAV_TIMEOUT_MS 处理；
# text_excerpt 截取上限：够人读，不占 verdict detail 太多。
_TEXT_EXCERPT_MAX = 200


@dataclass(frozen=True, slots=True)
class DomProbeResult:
    """DOM 探针三态结果（不可变值对象）。

    Attributes:
        found:        元素存在（且 expected_text 命中，若提供）
        text_excerpt: 元素附近文本摘录（调试 / verdict detail 用）；error 非空时为空串
        error:        诚实错误描述；非空 = unverifiable（浏览器不可用/超时/异常）
    """
    found: bool = False
    text_excerpt: str = ""
    error: str = ""


class DomProber:
    """DOM 断言探针：宿主侧只读验证器件。

    通过构造注入 BrowserController（None=未接入，所有 probe 调用直接返回 error）。
    线程安全：probe 序列化投命令到 BrowserController 内部队列（BrowserController 本身
    已保证线程安全）。
    """

    def __init__(self, browser: "BrowserController | None") -> None:
        self._browser = browser

    # ── 公开 API ────────────────────────────────────────────────────────────

    def probe(
        self,
        url: str | None,
        selector: str,
        *,
        expected_text: str | None = None,
        timeout_s: float = 15.0,  # 导航超时宽限（实际 hard limit 在 BrowserController）
    ) -> DomProbeResult:
        """执行 DOM 断言探针。

        Args:
            url:           要导航到的 URL；None 时跳过导航（用当前 page 状态）。
            selector:      CSS 选择器，用于定位目标元素。
            expected_text: 可选；若提供，元素文本必须包含此串才算 found=True。
            timeout_s:     超时提示（实际由 BrowserController 内部 Playwright timeout 执行）。

        Returns:
            DomProbeResult：三态结果（found / 证据摘录 / error）。
        """
        if self._browser is None:
            return DomProbeResult(
                found=False, text_excerpt="",
                error=t("verify.dom_probe.no_browser"),
            )
        try:
            return self._do_probe(url, selector, expected_text=expected_text)
        except Exception as exc:  # noqa: BLE001 — 任何异常 → unverifiable，诚实
            return DomProbeResult(
                found=False, text_excerpt="",
                error=t("verify.dom_probe.exception", exc_type=type(exc).__name__, exc=exc),
            )

    # ── 内部实现 ─────────────────────────────────────────────────────────────

    def _do_probe(
        self,
        url: str | None,
        selector: str,
        *,
        expected_text: str | None,
    ) -> DomProbeResult:
        """实际探针逻辑（异常由 probe() 捕获）。"""
        browser = self._browser
        assert browser is not None  # 已在 probe() 入口过滤

        # 1. 导航（若提供 URL）
        if url:
            nav_result = browser.navigate(url)
            if is_error_result(nav_result):  # locale 无关:英文工具错误以 "Error:" 起
                return DomProbeResult(
                    found=False, text_excerpt="",
                    error=t("verify.dom_probe.nav_failed", result=nav_result),
                )

        # 2. 抓 snapshot（BrowserController.snapshot → inner_text("body")）
        snapshot = browser.snapshot(max_chars=8000)
        if is_error_result(snapshot):  # locale 无关:英文工具错误以 "Error:" 起
            return DomProbeResult(
                found=False, text_excerpt="",
                error=t("verify.dom_probe.snapshot_failed", result=snapshot),
            )

        # 3. 证据强度分级（Major-1 修正）
        #    BrowserController 没有独立的 query_selector 接口；snapshot 返回 body inner_text。
        #    因此探针只能做"文本内容存在"断言，而非精确 DOM 查询。
        #
        #    强证据路径（有显式 expected_text）：
        #      - expected_text 完整出现在 body 文本 → found=True（passed）
        #      - 明确不出现 → found=False, error=""（failed，真实证据）
        #      这是声明式内容断言，调用方明确告知"页面应含此文本"，证据强度足够。
        #
        #    弱证据路径（无 expected_text，只有选择器派生的文本提示）：
        #      - 选择器文本提示在 body 中做子串匹配，命中不等于元素真实存在
        #        （'h1.headline' 的提示 'headline' 可能命中任意位置的 headline 字样），
        #        缺席也可能是假阴性（元素存在但无对应文本）。
        #      - 不论命中还是未命中，最高只能返回 unverifiable，绝不 passed / failed。
        #        detail 诚实写明"仅有文本弱提示，无结构性 DOM 校验通道，无法机检判定"。
        body_text = _extract_body_text(snapshot)

        if expected_text is not None:
            # ── 强证据路径：声明式 expected_text 内容断言 ────────────────
            if expected_text.lower() in body_text.lower():
                excerpt = _excerpt_around(body_text, expected_text)
                return DomProbeResult(found=True, text_excerpt=excerpt, error="")
            else:
                # 明确不出现 → failed（真实证据，非错误）
                return DomProbeResult(
                    found=False,
                    text_excerpt="",
                    error="",  # 非错误：正常执行，声明的文本确实不在页面中
                )
        else:
            # ── 弱证据路径：仅有选择器派生的文本提示，最高只能 unverifiable ──
            selector_text = _selector_to_text_hint(selector)
            detail = t(
                "verify.dom_probe.weak_evidence",
                selector=selector,
                hint=selector_text,
            )
            return DomProbeResult(found=False, text_excerpt="", error=detail)


# ── 工具函数 ──────────────────────────────────────────────────────────────────

# 从 CSS 选择器提取"最有意义的文本片段"，用于在 body text 中查找。
# 策略：提取最后一个可辨认的文本段（去掉 . # > + ~ [] : 等语法符号）。
_SELECTOR_CLEAN_RE = re.compile(r'[.#>\[\]:+~*=()\s]+')
_PSEUDO_RE = re.compile(r':[a-z-]+(\([^)]*\))?', re.I)


def _selector_to_text_hint(selector: str) -> str:
    """从 CSS 选择器提取最有意义的文本提示。

    Examples:
        "h1.headline"  → "headline"
        "#notification-badge" → "notification-badge"
        ".hero-title"  → "hero-title"
        "div > span.msg" → "msg"
        "body"         → "body"
    """
    # 去掉伪类（:hover, :nth-child(2)…）
    cleaned = _PSEUDO_RE.sub(' ', selector)
    # 按分隔符切分
    parts = _SELECTOR_CLEAN_RE.split(cleaned)
    # 取最后一个非空段
    meaningful = [p for p in parts if p and len(p) > 1]
    return meaningful[-1] if meaningful else selector.strip().lstrip('.#')


def _extract_body_text(snapshot: str) -> str:
    """从 BrowserController.snapshot 输出提取 body text 部分。

    snapshot 格式：
        [页面] <title>
        [URL] <url>

        <body text...>
    """
    lines = snapshot.split('\n')
    # 跳过前两行（[页面] / [URL] 头）
    body_lines = []
    skip = 0
    for line in lines:
        if line.startswith('[页面]') or line.startswith('[URL]'):
            skip += 1
            continue
        body_lines.append(line)
    return '\n'.join(body_lines).strip()


def _excerpt_around(text: str, keyword: str, window: int = _TEXT_EXCERPT_MAX) -> str:
    """在 text 中找 keyword，返回周围 window 字符的摘录（含省略号）。"""
    idx = text.find(keyword)
    if idx < 0:
        return text[:window]
    start = max(0, idx - window // 2)
    end = min(len(text), idx + len(keyword) + window // 2)
    excerpt = text[start:end]
    if start > 0:
        excerpt = "…" + excerpt
    if end < len(text):
        excerpt = excerpt + "…"
    return excerpt
