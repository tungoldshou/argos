"""Internal documentation."""
from __future__ import annotations

import os
import struct
import subprocess
import sys
import tempfile
import ctypes
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from argos.i18n import t as _t

if TYPE_CHECKING:
    from argos.perception.actions import ComputerAction


_DEFAULT_TIMEOUT = 10
_SCREENSHOT_TIMEOUT = 15

_ACCESS_DENIED_MARKERS = (
    "not allowed assistive access",
    "is not allowed to send keystrokes",
    "assistive access",
    "-1719",   # AppleScript error -1719 = can't get element
    "-25211",  # AXError: API Disabled
)

_ENV_FLAG = "ARGOS_COMPUTER_USE"




@dataclass(frozen=True, slots=True)
class ComputerActionResult:
    """Internal documentation."""
    ok: bool
    detail: str
    artifact_path: str | None = None
    size: tuple[int, int] | None = None



def _is_access_denied(stderr: str, stdout: str) -> bool:
    """Internal documentation."""
    combined = (stderr + stdout).lower()
    return any(m in combined for m in _ACCESS_DENIED_MARKERS)


def _screen_capture_allowed() -> bool:
    """Internal documentation."""
    if sys.platform != "darwin":
        return True
    try:
        cg = ctypes.CDLL("/System/Library/Frameworks/CoreGraphics.framework/CoreGraphics")
        check = cg.CGPreflightScreenCaptureAccess
        check.restype = ctypes.c_bool
        return bool(check())
    except Exception:  # noqa: BLE001
        return True



def detect_scale_factor(
    *,
    screenshot_width: int,
    logical_width: int,
) -> float:
    """Internal documentation."""
    if logical_width <= 0:
        return 1.0
    return float(screenshot_width) / float(logical_width)


def _png_width(path: str) -> int | None:
    """Internal documentation."""
    try:
        with open(path, "rb") as f:
            head = f.read(24)
        if head[:8] != b"\x89PNG\r\n\x1a\n":
            return None
        return struct.unpack(">I", head[16:20])[0]
    except Exception:  # noqa: BLE001
        return None


_SCALE_CACHE: dict[str, float] = {}


def detect_display_scale() -> float:
    """Internal documentation."""
    if "scale" in _SCALE_CACHE:
        return _SCALE_CACHE["scale"]
    scale = 1.0
    if sys.platform == "darwin":
        try:
            r = subprocess.run(
                ["osascript", "-e",
                 'tell application "Finder" to get bounds of window of desktop'],
                capture_output=True, text=True, timeout=5,
            )
            logical_w = 0
            if r.returncode == 0:
                nums = [int(p.strip()) for p in r.stdout.strip().split(",")
                        if p.strip().lstrip("-").isdigit()]
                if len(nums) >= 3:
                    logical_w = nums[2]
            physical_w = 0
            if logical_w > 0:
                with tempfile.NamedTemporaryFile(suffix=".png", delete=True) as tf:
                    sc = subprocess.run(["screencapture", "-x", tf.name],
                                        capture_output=True, timeout=_SCREENSHOT_TIMEOUT)
                    if sc.returncode == 0:
                        w = _png_width(tf.name)
                        if w:
                            physical_w = w
            if logical_w > 0 and physical_w > 0:
                scale = detect_scale_factor(screenshot_width=physical_w, logical_width=logical_w)
        except Exception:  # noqa: BLE001
            scale = 1.0
    _SCALE_CACHE["scale"] = scale
    return scale


class ComputerExecutor:
    """Internal documentation."""

    def __init__(self, *, timeout: int = _DEFAULT_TIMEOUT, scale_factor: float = 1.0,
                 auto_detect_scale: bool = False) -> None:
        """Internal documentation."""
        self._timeout = timeout
        self._scale_factor = scale_factor
        self._auto_detect_scale = auto_detect_scale
        self._scale_resolved = False

    def _effective_scale(self) -> float:
        """Internal documentation."""
        if (self._auto_detect_scale and not self._scale_resolved
                and os.environ.get("ARGOS_COMPUTER_USE")):
            self._scale_factor = detect_display_scale()
            self._scale_resolved = True
        return self._scale_factor


    def dispatch(self, action: "ComputerAction") -> ComputerActionResult:
        """Internal documentation."""
        if os.environ.get(_ENV_FLAG, "") != "1":
            return ComputerActionResult(ok=False, detail=_t("perception.executor.disabled"))

        kind = action.kind
        if kind == "screenshot":
            return self._screenshot()
        elif kind == "click":
            return self._click(action.x, action.y, double=False)
        elif kind == "double_click":
            return self._click(action.x, action.y, double=True)
        elif kind == "type_text":
            return self._type_text(action.text or "")
        elif kind == "key":
            return self._key(action.text or "")
        elif kind == "scroll":
            try:
                dy = int(action.text or "3")
            except ValueError:
                dy = 3
            return self._scroll(action.x, action.y, dy)
        elif kind == "open_app":
            return self._open_app(action.app or "")
        else:
            return ComputerActionResult(
                ok=False,
                detail=_t("perception.executor.unknown_kind", kind=kind),
            )


    def _run(
        self,
        cmd: list[str],
        *,
        timeout: int | None = None,
        input_text: str | None = None,
    ) -> tuple[int, str, str]:
        """Internal documentation."""
        t = timeout if timeout is not None else self._timeout
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=t,
                input=input_text,
            )
            return result.returncode, result.stdout, result.stderr
        except subprocess.TimeoutExpired:
            return -1, "", _t("perception.executor.timeout", cmd=cmd[0], t=t)
        except FileNotFoundError:
            return -1, "", _t("perception.executor.cmd_not_found", cmd=cmd[0])

    def _screenshot(self) -> ComputerActionResult:
        """Internal documentation."""
        if not _screen_capture_allowed():
            return ComputerActionResult(
                ok=False,
                detail=_t("perception.executor.screen_recording_denied"),
            )

        tmp = tempfile.NamedTemporaryFile(
            suffix=".png", prefix="argos_screen_", delete=False
        )
        tmp.close()
        path = tmp.name

        rc, _out, err = self._run(
            ["screencapture", "-x", path],
            timeout=_SCREENSHOT_TIMEOUT,
        )
        if rc != 0:
            try:
                Path(path).unlink(missing_ok=True)
            except OSError:
                pass
            return ComputerActionResult(
                ok=False,
                detail=_t("perception.executor.screenshot_failed",
                          rc=rc, err=err.strip() or _t("perception.executor.unknown_error")),
            )

        size: tuple[int, int] | None = None
        try:
            from PIL import Image  # type: ignore[import]
            with Image.open(path) as img:
                size = img.size  # (width, height)
        except Exception:
            size = (0, 0)

        return ComputerActionResult(
            ok=True,
            detail=_t("perception.executor.screenshot_saved", path=path),
            artifact_path=path,
            size=size,
        )

    def _click(self, x: int | None, y: int | None, *, double: bool) -> ComputerActionResult:
        """Internal documentation."""
        action_word = "double click" if double else "click"
        _scale = self._effective_scale()
        lx = round(x / _scale) if x is not None else x
        ly = round(y / _scale) if y is not None else y
        script = (
            f'tell application "System Events"\n'
            f'    {action_word} at {{x:{lx}, y:{ly}}}\n'
            f'end tell'
        )
        rc, out, err = self._run(["osascript", "-e", script])
        if rc != 0:
            if _is_access_denied(err, out):
                return ComputerActionResult(ok=False, detail=_t("perception.executor.access_denied"))
            _err_str = err.strip() or out.strip() or _t("perception.executor.unknown_error")
            _key = "perception.executor.double_click_failed" if double else "perception.executor.click_failed"
            return ComputerActionResult(
                ok=False,
                detail=_t(_key, rc=rc, err=_err_str),
            )
        _ok_key = "perception.executor.double_click_ok" if double else "perception.executor.click_ok"
        return ComputerActionResult(
            ok=True,
            detail=_t(_ok_key, lx=lx, ly=ly),
        )

    def _type_text(self, text: str) -> ComputerActionResult:
        """Internal documentation."""
        escaped = text.replace("\\", "\\\\").replace('"', '\\"')
        script = (
            f'tell application "System Events"\n'
            f'    keystroke "{escaped}"\n'
            f'end tell'
        )
        rc, out, err = self._run(["osascript", "-e", script])
        if rc != 0:
            if _is_access_denied(err, out):
                return ComputerActionResult(ok=False, detail=_t("perception.executor.access_denied"))
            return ComputerActionResult(
                ok=False,
                detail=_t("perception.executor.type_text_failed",
                           rc=rc, err=err.strip() or out.strip() or _t("perception.executor.unknown_error")),
            )
        preview = text[:40] + ("…" if len(text) > 40 else "")
        return ComputerActionResult(ok=True, detail=_t("perception.executor.type_text_ok", preview=preview))

    def _key(self, key_combo: str) -> ComputerActionResult:
        """Internal documentation."""
        parts = [p.strip().lower() for p in key_combo.split("+")]
        main_key = parts[-1]
        modifiers = parts[:-1]

        modifier_map = {
            "command": "command key",
            "cmd": "command key",
            "shift": "shift key",
            "option": "option key",
            "alt": "option key",
            "control": "control key",
            "ctrl": "control key",
        }
        using_parts = [modifier_map[m] for m in modifiers if m in modifier_map]

        escaped_main = main_key.replace("\\", "\\\\").replace('"', '\\"')
        if using_parts:
            using_clause = " using {" + ", ".join(using_parts) + "}"
        else:
            using_clause = ""

        script = (
            f'tell application "System Events"\n'
            f'    keystroke "{escaped_main}"{using_clause}\n'
            f'end tell'
        )
        rc, out, err = self._run(["osascript", "-e", script])
        if rc != 0:
            if _is_access_denied(err, out):
                return ComputerActionResult(ok=False, detail=_t("perception.executor.access_denied"))
            return ComputerActionResult(
                ok=False,
                detail=_t("perception.executor.key_failed",
                           rc=rc, err=err.strip() or out.strip() or _t("perception.executor.unknown_error")),
            )
        return ComputerActionResult(ok=True, detail=_t("perception.executor.key_ok", combo=key_combo))

    def _scroll(self, x: int | None, y: int | None, dy: int) -> ComputerActionResult:
        """Internal documentation."""
        _scale = self._effective_scale()
        lx = round(x / _scale) if x is not None else x
        ly = round(y / _scale) if y is not None else y
        script = (
            f'tell application "System Events"\n'
            f'    scroll (a reference to the front window) by {dy} using at {{x:{lx}, y:{ly}}}\n'
            f'end tell'
        )
        rc, out, err = self._run(["osascript", "-e", script])
        if rc != 0:
            if _is_access_denied(err, out):
                return ComputerActionResult(ok=False, detail=_t("perception.executor.access_denied"))
            return ComputerActionResult(
                ok=False,
                detail=_t("perception.executor.scroll_failed",
                           rc=rc, err=err.strip() or out.strip() or _t("perception.executor.unknown_error")),
            )
        return ComputerActionResult(ok=True, detail=_t("perception.executor.scroll_ok", lx=lx, ly=ly, dy=dy))

    def _open_app(self, app: str) -> ComputerActionResult:
        """Internal documentation."""
        rc, _out, err = self._run(["open", "-a", app])
        if rc != 0:
            return ComputerActionResult(
                ok=False,
                detail=_t("perception.executor.open_app_failed",
                           app=app, rc=rc,
                           err=err.strip() or _t("perception.executor.open_app_no_permission")),
            )
        return ComputerActionResult(ok=True, detail=_t("perception.executor.open_app_ok", app=app))
