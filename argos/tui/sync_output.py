from __future__ import annotations

import os
import re
import select
import sys
import termios
import time
import tty
from contextlib import contextmanager
from typing import Iterator, TextIO

CSI_BSU = "\x1b[?2026h"   # Begin Synchronized Update
CSI_ESU = "\x1b[?2026l"   # End Synchronized Update
CSI_QUERY = "\x1b[?2026$p"

# Ps = 0 not recognized
# Ps = 1 recognized, currently set
# Ps = 2 recognized, permanently reset
# Ps = 3 recognized, not permanently reset
# Ps = 4 not available
_RE_DECTRQM = re.compile(r"\x1b\[\?2026(?:\s*;\s*([0-4]))?\$y")
_SUPPORTED_PS = frozenset({1, 2, 3})


def _is_tty(stream: TextIO | None) -> bool:
    if stream is None:
        return False
    try:
        return bool(stream.isatty())
    except (AttributeError, ValueError):
        return False


def _parse_dectrqm_reply(reply: str) -> bool | None:
    if not reply:
        return None
    m = _RE_DECTRQM.search(reply)
    if not m:
        return None
    ps_str = m.group(1)
    if ps_str is None:
        return False
    return int(ps_str) in _SUPPORTED_PS


def _query_mode_2026(timeout_s: float) -> str | None:
    try:
        fd_in = sys.stdin.fileno()
        fd_out = sys.stdout.fileno()
    except (AttributeError, OSError):
        return None

    try:
        old_settings = termios.tcgetattr(fd_in)
    except (termios.error, OSError):
        return None

    reply_parts: list[str] = []
    try:
        tty.setraw(fd_in)

        while True:
            r, _, _ = select.select([fd_in], [], [], 0)
            if not r:
                break
            try:
                data = os.read(fd_in, 4096)
            except OSError:
                break
            if not data:
                break  # EOF

        try:
            os.write(fd_out, CSI_QUERY.encode("ascii"))
        except OSError:
            return None

        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline:
            remaining = max(0.0, deadline - time.monotonic())
            r, _, _ = select.select([fd_in], [], [], remaining)
            if not r:
                break
            try:
                chunk = os.read(fd_in, 4096).decode("utf-8", errors="replace")
            except OSError:
                break
            if not chunk:
                break
            reply_parts.append(chunk)
            if "$y" in "".join(reply_parts):
                break

        return "".join(reply_parts) or None
    finally:
        try:
            termios.tcsetattr(fd_in, termios.TCSADRAIN, old_settings)
        except (termios.error, OSError):
            pass


_probe_cache: bool | None = None


def probe_sync_output(
    stream: TextIO | None = None,
    timeout_s: float = 0.05,
) -> bool:
    global _probe_cache
    if _probe_cache is not None:
        return _probe_cache

    if stream is None:
        stream = sys.stdout
    if not _is_tty(stream):
        return False
    if not _is_tty(sys.stdin):
        return False

    reply = _query_mode_2026(timeout_s)
    if reply is None:
        return False
    parsed = _parse_dectrqm_reply(reply)
    if parsed is None:
        return False

    _probe_cache = parsed
    return parsed


def clear_probe_cache() -> None:
    global _probe_cache
    _probe_cache = None


@contextmanager
def sync_batch(
    stream: TextIO,
    enabled: bool | None = None,
) -> Iterator[None]:
    if enabled is None:
        enabled = probe_sync_output(stream)

    if not enabled:
        yield
        return

    try:
        stream.write(CSI_BSU)
        stream.flush()
    except Exception:
        try:
            stream.write(CSI_ESU)
            stream.flush()
        except Exception:
            pass
        raise

    try:
        yield
    finally:
        try:
            stream.write(CSI_ESU)
            stream.flush()
        except Exception:
            pass