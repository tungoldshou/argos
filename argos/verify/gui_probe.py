"""argos/verify/gui_probe.py —— GUI 断言探针(验证梯子,computer-use 版)。

host 侧【只读、独立】验证器件:给定 expected_text,截屏 + OCR,断言该文本出现在屏上。
**绝不被 agent 代码控制**——探针在 host 侧 verify 阶段调用,沙箱代码影响不了它。

护城河关键设计(独立性):用 **OCR(确定性、与被验模型无关)** 做断言,**绝不**反过来问
同一个模型"你成功了吗"——那是循环自证,等于让被告当法官,会把 verify 硬门掏空。

三态承诺(诚实不变量,对齐 DomProber):
  · found=True            → expected_text 出现在 OCR 文本 → passed
  · found=False, error="" → expected_text 明确不出现 → failed(真实证据)
  · error 非空            → OCR 不可用 / 截图失败 / 无 expected_text / 异常 → unverifiable(诚实降级)

设计约束:
  · OCR 走可选依赖 pytesseract + Pillow;任一缺失 → 返回 error(unverifiable),绝不假装 passed。
  · executor=None(未接入)→ 直接 error(向后兼容:验证梯子跳过 GUI 策略)。
  · 截图经 ComputerExecutor(ARGOS_COMPUTER_USE 未开时它自身返禁止消息 → ok=False → unverifiable)。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from argos.i18n import t

if TYPE_CHECKING:
    from argos.perception.executor import ComputerExecutor

_TEXT_EXCERPT_MAX = 200


@dataclass(frozen=True, slots=True)
class GuiProbeResult:
    """GUI 探针三态结果(不可变值对象,对齐 DomProbeResult)。

    found:        expected_text 命中 OCR 文本。
    text_excerpt: 命中处周围文本摘录(verdict detail 用);error 非空时为空串。
    error:        诚实错误描述;非空 = unverifiable(OCR 不可用/截图失败/异常)。
    """
    found: bool = False
    text_excerpt: str = ""
    error: str = ""


class GuiProber:
    """GUI 断言探针:宿主侧只读、独立(OCR)验证器件。

    通过构造注入 ComputerExecutor(None=未接入,所有 probe 直接返回 error)。
    """

    def __init__(self, executor: "ComputerExecutor | None") -> None:
        self._executor = executor

    def probe(self, expected_text: str | None, *, timeout_s: float = 15.0) -> GuiProbeResult:
        """截屏 + OCR,断言 expected_text 出现。三态返回。

        Args:
            expected_text: 屏上应出现的文本(声明式内容断言)。None/空 → unverifiable。
            timeout_s:     预留;截图超时由 ComputerExecutor 内部处理。
        """
        if not expected_text:
            return GuiProbeResult(
                error=t("verify.gui_probe.no_expected_text"),
            )
        if self._executor is None:
            return GuiProbeResult(error=t("verify.gui_probe.no_executor"))
        try:
            from argos.perception.actions import ComputerAction
            shot = self._executor.dispatch(ComputerAction(kind="screenshot"))
            if not getattr(shot, "ok", False) or not getattr(shot, "artifact_path", None):
                return GuiProbeResult(error=t(
                    "verify.gui_probe.screenshot_failed",
                    detail=getattr(shot, "detail", "?"),
                ))
            text = _ocr(shot.artifact_path)
            if text is None:
                return GuiProbeResult(
                    error=t("verify.gui_probe.ocr_unavailable"),
                )
            if expected_text.lower() in text.lower():
                return GuiProbeResult(found=True, text_excerpt=_excerpt_around(text, expected_text))
            # 明确不出现 → failed(真实证据,非错误)
            return GuiProbeResult(found=False, text_excerpt="", error="")
        except Exception as exc:  # noqa: BLE001 — 任何异常 → unverifiable,诚实
            return GuiProbeResult(error=t(
                "verify.gui_probe.exception",
                exc_type=type(exc).__name__,
                exc=exc,
            ))


def _ocr(path: str) -> str | None:
    """对截图做 OCR,返回识别文本;依赖缺失/失败 → None(调用方据此判 unverifiable)。"""
    try:
        import pytesseract  # type: ignore[import]
        from PIL import Image  # type: ignore[import]
        with Image.open(path) as img:
            return pytesseract.image_to_string(img)
    except Exception:  # noqa: BLE001 — pytesseract/tesseract 缺失或 OCR 失败 → 诚实 None
        return None


def _excerpt_around(text: str, keyword: str, window: int = _TEXT_EXCERPT_MAX) -> str:
    """在 text 中找 keyword(忽略大小写),返回周围 window 字符的摘录(含省略号)。"""
    low = text.lower()
    idx = low.find(keyword.lower())
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
