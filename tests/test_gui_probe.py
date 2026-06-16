"""GuiProber 三态铁证(2d GUI 验证核心):OCR 独立断言屏上文本,绝不问模型自证。
passed/failed/unverifiable 全覆盖;OCR/截图/接入缺失 → 诚实 unverifiable,绝不假 passed。
OCR 用 monkeypatch 注入(本环境无 pytesseract;真 OCR 属用户侧)。"""
from __future__ import annotations

from argos.verify import gui_probe
from argos.verify.gui_probe import GuiProber, GuiProbeResult


class _Shot:
    def __init__(self, ok=True, detail="截图已保存", artifact_path="/tmp/x.png"):
        self.ok = ok
        self.detail = detail
        self.artifact_path = artifact_path


class _Exec:
    """fake ComputerExecutor:dispatch(screenshot) → 给定结果。"""
    def __init__(self, shot):
        self._shot = shot
    def dispatch(self, ca):
        return self._shot


def test_passed_when_expected_text_in_ocr(monkeypatch):
    monkeypatch.setattr(gui_probe, "_ocr", lambda p: "Login successful — Welcome back")
    r = GuiProber(_Exec(_Shot())).probe("welcome back")   # 忽略大小写
    assert r.found is True and r.error == "" and "Welcome back" in r.text_excerpt


def test_failed_when_expected_text_absent(monkeypatch):
    monkeypatch.setattr(gui_probe, "_ocr", lambda p: "Error: invalid credentials")
    r = GuiProber(_Exec(_Shot())).probe("welcome back")
    assert r.found is False and r.error == ""              # 明确不出现 = failed(真实证据)


def test_unverifiable_when_ocr_unavailable(monkeypatch):
    monkeypatch.setattr(gui_probe, "_ocr", lambda p: None)  # 无 pytesseract
    r = GuiProber(_Exec(_Shot())).probe("anything")
    assert r.found is False and "OCR" in r.error           # 诚实 unverifiable,不假 passed


def test_unverifiable_when_screenshot_fails():
    r = GuiProber(_Exec(_Shot(ok=False, detail="计算机控制未启用", artifact_path=None))).probe("x")
    assert r.found is False and "截图失败" in r.error


def test_unverifiable_when_no_executor():
    r = GuiProber(None).probe("x")
    assert r.found is False and "未接入" in r.error


def test_unverifiable_when_no_expected_text():
    r = GuiProber(_Exec(_Shot())).probe(None)
    assert r.found is False and "expected_text" in r.error


def test_probe_exception_degrades_to_unverifiable(monkeypatch):
    def _boom(p):
        raise RuntimeError("ocr blew up")
    monkeypatch.setattr(gui_probe, "_ocr", _boom)
    r = GuiProber(_Exec(_Shot())).probe("x")
    assert r.found is False and "异常" in r.error          # 异常 → 诚实降级,不崩
