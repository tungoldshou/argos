from __future__ import annotations

from argos.verify import gui_probe
from argos.verify.gui_probe import GuiProber, GuiProbeResult


class _Shot:
    def __init__(self, ok=True, detail="截图已保存", artifact_path="/tmp/x.png"):
        self.ok = ok
        self.detail = detail
        self.artifact_path = artifact_path


class _Exec:
    def __init__(self, shot):
        self._shot = shot
    def dispatch(self, ca):
        return self._shot


def test_passed_when_expected_text_in_ocr(monkeypatch):
    monkeypatch.setattr(gui_probe, "_ocr", lambda p: "Login successful — Welcome back")
    r = GuiProber(_Exec(_Shot())).probe("welcome back")
    assert r.found is True and r.error == "" and "Welcome back" in r.text_excerpt


def test_failed_when_expected_text_absent(monkeypatch):
    monkeypatch.setattr(gui_probe, "_ocr", lambda p: "Error: invalid credentials")
    r = GuiProber(_Exec(_Shot())).probe("welcome back")
    assert r.found is False and r.error == ""


def test_unverifiable_when_ocr_unavailable(monkeypatch):
    monkeypatch.setattr(gui_probe, "_ocr", lambda p: None)
    r = GuiProber(_Exec(_Shot())).probe("anything")
    assert r.found is False and "OCR" in r.error


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
    assert r.found is False and "异常" in r.error
