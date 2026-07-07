from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from argos.i18n import t
from argos.input.attachments import (
    ImageAttachment, sniff_media_type,
)


class ClipboardError(Exception):
    pass


def _parse_macos_png_data(text: str) -> bytes:
    raw = text.strip()
    prefix = "«data PNGf"
    suffix = "»"
    if not raw.startswith(prefix) or not raw.endswith(suffix):
        raise ClipboardError(t("input.clipboard.bad_format"))
    hex_data = "".join(raw[len(prefix):-len(suffix)].split())
    try:
        return bytes.fromhex(hex_data)
    except ValueError as e:
        raise ClipboardError(t("input.clipboard.bad_format")) from e


def _check_osascript() -> None:
    if shutil.which("osascript") is None:
        raise ClipboardError(t("input.clipboard.no_image_macos"))


def _applescript_string(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')


def _read_macos_osascript_file() -> bytes:
    _check_osascript()
    with tempfile.TemporaryDirectory() as td:
        out_path = Path(td) / "clipboard.png"
        try:
            proc = subprocess.run(
                [
                    "osascript",
                    "-e", "set pngData to the clipboard as «class PNGf»",
                    "-e", (
                        "set outFile to open for access POSIX file "
                        f'"{_applescript_string(str(out_path))}" with write permission'
                    ),
                    "-e", "set eof of outFile to 0",
                    "-e", "write pngData to outFile",
                    "-e", "close access outFile",
                ],
                capture_output=True,
                text=True,
                timeout=10,
            )
        except (OSError, subprocess.SubprocessError) as e:
            raise ClipboardError(t("input.clipboard.no_image_macos")) from e
        if proc.returncode != 0 or not out_path.exists():
            raise ClipboardError(t("input.clipboard.no_image_macos"))
        data = out_path.read_bytes()
        if not data:
            raise ClipboardError(t("input.clipboard.no_image_macos"))
        return data


def _read_macos_osascript_hex() -> bytes:
    _check_osascript()
    script = "the clipboard as «class PNGf»"
    try:
        proc = subprocess.run(
            ["osascript", "-e", script],
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError) as e:
        raise ClipboardError(t("input.clipboard.no_image_macos")) from e
    if proc.returncode != 0 or not proc.stdout.strip():
        raise ClipboardError(t("input.clipboard.no_image_macos"))
    return _parse_macos_png_data(proc.stdout)


def _read_macos_osascript() -> bytes:
    try:
        return _read_macos_osascript_file()
    except ClipboardError as first_error:
        try:
            return _read_macos_osascript_hex()
        except ClipboardError:
            raise first_error


def _read_macos_pngpaste() -> bytes:
    if shutil.which("pngpaste") is None:
        raise ClipboardError(t("input.clipboard.no_image_macos"))
    proc = subprocess.run(["pngpaste", "-"], capture_output=True, timeout=10)
    if proc.returncode != 0 or not proc.stdout:
        raise ClipboardError(t("input.clipboard.no_image_macos"))
    return proc.stdout


def _read_bytes() -> bytes:
    if sys.platform == "darwin":
        try:
            return _read_macos_osascript()
        except ClipboardError as first_error:
            try:
                return _read_macos_pngpaste()
            except ClipboardError:
                raise first_error
    if sys.platform.startswith("linux"):
        if shutil.which("xclip") is None:
            raise ClipboardError(t("input.clipboard.need_xclip"))
        proc = subprocess.run(
            ["xclip", "-selection", "clipboard", "-t", "image/png", "-o"],
            capture_output=True, timeout=10,
        )
        if proc.returncode != 0 or not proc.stdout:
            raise ClipboardError(t("input.clipboard.no_image_linux"))
        return proc.stdout
    raise ClipboardError(t("input.clipboard.unsupported_platform", platform=sys.platform))


def read_clipboard_image() -> ImageAttachment:
    data = _read_bytes()
    try:
        media = sniff_media_type(data)
    except ValueError as e:
        raise ClipboardError(t("input.clipboard.bad_format")) from e
    return ImageAttachment(data=data, media_type=media, source_label="clipboard")


def read_clipboard_text() -> str:
    try:
        if sys.platform == "darwin":
            proc = subprocess.run(["pbpaste"], capture_output=True, text=True, timeout=10)
        elif sys.platform.startswith("linux"):
            if shutil.which("xclip") is None:
                return ""
            proc = subprocess.run(
                ["xclip", "-selection", "clipboard", "-o"],
                capture_output=True, text=True, timeout=10,
            )
        else:
            return ""
    except (OSError, subprocess.SubprocessError):
        return ""
    if proc.returncode != 0:
        return ""
    return proc.stdout
