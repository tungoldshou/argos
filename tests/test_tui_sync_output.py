"""Internal documentation."""
from __future__ import annotations

import io

import pytest

from argos.tui import sync_output
from argos.tui.sync_output import (
    CSI_BSU,
    CSI_ESU,
    clear_probe_cache,
    probe_sync_output,
    sync_batch,
)


@pytest.fixture(autouse=True)
def _reset_probe_cache():
    """Internal documentation."""
    clear_probe_cache()
    yield
    clear_probe_cache()



def test_csi_bsu_matches_xterm_extension():
    """Internal documentation."""
    assert CSI_BSU == "\x1b[?2026h"


def test_csi_esu_matches_xterm_extension():
    """Internal documentation."""
    assert CSI_ESU == "\x1b[?2026l"


# ───── probe_sync_output ─────

def test_probe_returns_false_when_stream_not_tty():
    """Internal documentation."""
    assert probe_sync_output(stream=io.StringIO()) is False


def test_probe_returns_false_when_stdin_not_tty(monkeypatch):
    """Internal documentation."""
    fake_out = _make_fake_tty()
    fake_in = io.StringIO()
    monkeypatch.setattr(sync_output.sys, "stdin", fake_in)
    assert probe_sync_output(stream=fake_out) is False


def test_probe_returns_false_on_query_timeout(monkeypatch):
    """Internal documentation."""
    monkeypatch.setattr(sync_output, "_query_mode_2026", lambda _t: None)
    _patch_fake_tty(monkeypatch)
    assert probe_sync_output(stream=_make_fake_tty()) is False


def test_probe_returns_true_for_ps_1(monkeypatch):
    """Internal documentation."""
    monkeypatch.setattr(
        sync_output, "_query_mode_2026",
        lambda _t: "\x1b[?2026;1$y",
    )
    _patch_fake_tty(monkeypatch)
    assert probe_sync_output(stream=_make_fake_tty()) is True


def test_probe_returns_true_for_ps_2(monkeypatch):
    """Internal documentation."""
    monkeypatch.setattr(
        sync_output, "_query_mode_2026",
        lambda _t: "\x1b[?2026;2$y",
    )
    _patch_fake_tty(monkeypatch)
    assert probe_sync_output(stream=_make_fake_tty()) is True


def test_probe_returns_false_for_ps_0(monkeypatch):
    """Internal documentation."""
    monkeypatch.setattr(
        sync_output, "_query_mode_2026",
        lambda _t: "\x1b[?2026;0$y",
    )
    _patch_fake_tty(monkeypatch)
    assert probe_sync_output(stream=_make_fake_tty()) is False


def test_probe_returns_false_for_garbage_reply(monkeypatch):
    """Internal documentation."""
    monkeypatch.setattr(
        sync_output, "_query_mode_2026",
        lambda _t: "garbage\x1b[?2027;2$y",
    )
    _patch_fake_tty(monkeypatch)
    assert probe_sync_output(stream=_make_fake_tty()) is False


def test_probe_returns_false_for_empty_reply(monkeypatch):
    """Internal documentation."""
    monkeypatch.setattr(sync_output, "_query_mode_2026", lambda _t: "")
    _patch_fake_tty(monkeypatch)
    assert probe_sync_output(stream=_make_fake_tty()) is False


def test_probe_returns_false_when_reply_omits_numeric(monkeypatch):
    """Internal documentation."""
    monkeypatch.setattr(
        sync_output, "_query_mode_2026",
        lambda _t: "\x1b[?2026$y",
    )
    _patch_fake_tty(monkeypatch)
    assert probe_sync_output(stream=_make_fake_tty()) is False


def test_probe_returns_false_for_ps_4(monkeypatch):
    """DECRQM Ps=4 (not available) → False。"""
    monkeypatch.setattr(
        sync_output, "_query_mode_2026",
        lambda _t: "\x1b[?2026;4$y",
    )
    _patch_fake_tty(monkeypatch)
    assert probe_sync_output(stream=_make_fake_tty()) is False


def test_probe_returns_false_when_stream_is_none():
    """Internal documentation."""
    assert probe_sync_output(stream=None) is False


def test_probe_returns_false_when_isatty_raises():
    """Internal documentation."""
    class FlakyStream:
        def isatty(self):
            raise AttributeError("flaky")
        def write(self, _s): pass  # noqa: ARG002
        def flush(self): pass  # noqa: ARG002
    assert probe_sync_output(stream=FlakyStream()) is False



def test_is_tty_returns_false_for_none():
    """Internal documentation."""
    assert sync_output._is_tty(None) is False  # noqa: SLF001


def test_is_tty_returns_false_when_isatty_raises_attribute_error():
    """Internal documentation."""
    class Flaky:
        def isatty(self):
            raise AttributeError
    assert sync_output._is_tty(Flaky()) is False  # noqa: SLF001


def test_is_tty_returns_true_for_stringio_with_isatty_true():
    """StringIO + isatty=True → True。"""
    s = io.StringIO()
    s.isatty = lambda: True  # type: ignore[assignment]
    assert sync_output._is_tty(s) is True  # noqa: SLF001


def test_is_tty_returns_false_when_isatty_raises_value_error():
    """Internal documentation."""
    class ClosedFileLike:
        def isatty(self):
            raise ValueError("I/O operation on closed file")
        def write(self, _s): pass  # noqa: ARG002
        def flush(self): pass  # noqa: ARG002
    assert sync_output._is_tty(ClosedFileLike()) is False  # noqa: SLF001



def test_probe_caches_result_across_calls(monkeypatch):
    """Internal documentation."""
    call_count = {"n": 0}

    def fake_query(_t):
        call_count["n"] += 1
        return "\x1b[?2026;2$y"

    _patch_fake_tty(monkeypatch)
    monkeypatch.setattr(sync_output, "_query_mode_2026", fake_query)

    r1 = probe_sync_output(stream=_make_fake_tty())
    r2 = probe_sync_output(stream=_make_fake_tty())
    r3 = probe_sync_output(stream=_make_fake_tty())

    assert r1 is True and r2 is True and r3 is True
    assert call_count["n"] == 1, (
        f"3 次 probe 应只调 1 次 _query_mode_2026,实际 {call_count['n']} 次"
    )


def test_probe_cache_can_be_cleared(monkeypatch):
    """Internal documentation."""
    call_count = {"n": 0}

    def fake_query(_t):
        call_count["n"] += 1
        return "\x1b[?2026;2$y"

    _patch_fake_tty(monkeypatch)
    monkeypatch.setattr(sync_output, "_query_mode_2026", fake_query)

    probe_sync_output(stream=_make_fake_tty())
    probe_sync_output(stream=_make_fake_tty())
    assert call_count["n"] == 1

    clear_probe_cache()
    probe_sync_output(stream=_make_fake_tty())
    assert call_count["n"] == 2, "clear_probe_cache 后应重新探测"

    clear_probe_cache()
    probe_sync_output(stream=_make_fake_tty())
    assert call_count["n"] == 3, "再 clear + probe 应再 +1"


def test_probe_cache_stores_false_too(monkeypatch):
    """Internal documentation."""
    call_count = {"n": 0}

    def fake_query(_t):
        call_count["n"] += 1
        return "\x1b[?2026;0$y"  # not recognized

    _patch_fake_tty(monkeypatch)
    monkeypatch.setattr(sync_output, "_query_mode_2026", fake_query)

    r1 = probe_sync_output(stream=_make_fake_tty())
    r2 = probe_sync_output(stream=_make_fake_tty())

    assert r1 is False and r2 is False
    assert call_count["n"] == 1


def test_probe_cache_does_not_interfere_with_non_tty_fast_path(monkeypatch):
    """Internal documentation."""
    call_count = {"n": 0}

    def fake_query(_t):
        call_count["n"] += 1
        return "\x1b[?2026;2$y"

    _patch_fake_tty(monkeypatch)
    monkeypatch.setattr(sync_output, "_query_mode_2026", fake_query)

    r1 = probe_sync_output(stream=io.StringIO())
    assert r1 is False
    assert call_count["n"] == 0, "非 TTY 短路应直接返,不应触发 probe"

    r2 = probe_sync_output(stream=_make_fake_tty())
    assert r2 is True
    assert call_count["n"] == 1


# ───── sync_batch ─────

def test_sync_batch_emits_brackets_when_enabled():
    """Internal documentation."""
    buf = io.StringIO()
    with sync_batch(buf, enabled=True):
        buf.write("hello")
    assert buf.getvalue() == CSI_BSU + "hello" + CSI_ESU


def test_sync_batch_is_noop_when_disabled():
    """Internal documentation."""
    buf = io.StringIO()
    with sync_batch(buf, enabled=False):
        buf.write("hello")
    assert buf.getvalue() == "hello"


def test_sync_batch_emits_esu_on_exception():
    """Internal documentation."""
    buf = io.StringIO()
    with pytest.raises(RuntimeError, match="boom"):
        with sync_batch(buf, enabled=True):
            buf.write("partial")
            raise RuntimeError("boom")
    assert buf.getvalue() == CSI_BSU + "partial" + CSI_ESU


def test_sync_batch_empty_block_still_emits_esu():
    """Internal documentation."""
    buf = io.StringIO()
    with sync_batch(buf, enabled=True):
        pass
    assert buf.getvalue() == CSI_BSU + CSI_ESU


def test_sync_batch_passes_through_multiple_writes():
    """Internal documentation."""
    buf = io.StringIO()
    with sync_batch(buf, enabled=True):
        buf.write("a")
        buf.write("b")
        buf.write("\n")
        buf.write("c")
    assert buf.getvalue() == CSI_BSU + "ab\nc" + CSI_ESU


def test_sync_batch_none_auto_probes_unsupported(monkeypatch):
    """Internal documentation."""
    monkeypatch.setattr(sync_output, "probe_sync_output", lambda _s: False)
    buf = io.StringIO()
    with sync_batch(buf):
        buf.write("hello")
    assert buf.getvalue() == "hello"


def test_sync_batch_none_auto_probes_supported(monkeypatch):
    """Internal documentation."""
    monkeypatch.setattr(sync_output, "probe_sync_output", lambda _s: True)
    buf = io.StringIO()
    with sync_batch(buf):
        buf.write("hello")
    assert buf.getvalue() == CSI_BSU + "hello" + CSI_ESU


def test_sync_batch_does_not_probe_when_enabled_explicit(monkeypatch):
    """Internal documentation."""
    called = {"count": 0}
    def fake_probe(_s):
        called["count"] += 1
        return True
    monkeypatch.setattr(sync_output, "probe_sync_output", fake_probe)
    buf = io.StringIO()
    with sync_batch(buf, enabled=True):
        buf.write("x")
    assert called["count"] == 0, "显式 enabled 时不应现场探测"



def test_sync_batch_emits_esu_recovery_when_bsu_flush_fails():
    """Internal documentation."""
    written: list[str] = []
    state = {"flush_count": 0}

    class FlakyStream:
        def write(self, s):
            written.append(s)
        def flush(self):
            state["flush_count"] += 1
            if state["flush_count"] == 1:
                raise OSError("disk full on BSU flush")

    buf = FlakyStream()
    with pytest.raises(OSError, match="disk full"):
        with sync_batch(buf, enabled=True):
            pass

    assert CSI_BSU in written, "BSU 应该已经被尝试写出"
    assert CSI_ESU in written, "BSU flush 失败时仍应尽力发 ESU 恢复"
    assert written.index(CSI_BSU) < written.index(CSI_ESU), (
        "ESU 必须在 BSU 之后(恢复路径)"
    )


def test_sync_batch_emits_esu_recovery_when_bsu_write_fails():
    """Internal documentation."""
    written: list[str] = []
    state = {"write_count": 0}

    class FlakyStream:
        def write(self, s):
            state["write_count"] += 1
            if state["write_count"] == 1:
                raise OSError("broken pipe on BSU write")
            written.append(s)
        def flush(self):
            pass

    buf = FlakyStream()
    with pytest.raises(OSError, match="broken pipe"):
        with sync_batch(buf, enabled=True):
            pass

    assert CSI_ESU in written, "BSU write 失败后仍应尝试发 ESU"
    assert state["write_count"] >= 2, "应该至少调用过 2 次 write(BSU+ESU)"


def test_sync_batch_recovery_silently_swallows_esu_failures():
    """Internal documentation."""
    state = {"flush_count": 0}

    class DoomedStream:
        def write(self, _s):
            pass
        def flush(self):
            state["flush_count"] += 1
            if state["flush_count"] == 1:
                raise OSError("BSU flush failed")
            raise OSError("ESU flush also failed")

    buf = DoomedStream()
    with pytest.raises(OSError, match="BSU flush failed"):
        with sync_batch(buf, enabled=True):
            pass



def test_query_mode_2026_joins_split_terminator(monkeypatch):
    """Internal documentation."""
    class FakeTermiosError(Exception):
        pass

    class FakeTermios:
        TCSADRAIN = 1
        error = FakeTermiosError

        @staticmethod
        def tcgetattr(_fd):
            return [0] * 20

        @staticmethod
        def tcsetattr(_fd, _when, _settings):
            pass

    class FakeTty:
        @staticmethod
        def setraw(_fd):
            pass

    monkeypatch.setattr(sync_output, "termios", FakeTermios)
    monkeypatch.setattr(sync_output, "tty", FakeTty)

    chunks_data = [
        b"\x1b[?2026;2$",
        b"y",
    ]
    state = {"read_idx": 0}

    def fake_select(rlist, wlist, xlist, timeout):
        if timeout == 0:
            return ([], [], [])
        if state["read_idx"] < len(chunks_data):
            return ([1], [], [])
        return ([], [], [])

    monkeypatch.setattr(sync_output.select, "select", fake_select)
    monkeypatch.setattr(sync_output.os, "write", lambda _fd, data: len(data))

    def fake_read(_fd, _n):
        if state["read_idx"] < len(chunks_data):
            c = chunks_data[state["read_idx"]]
            state["read_idx"] += 1
            return c
        return b""  # EOF

    monkeypatch.setattr(sync_output.os, "read", fake_read)

    class FakeStream:
        def fileno(self):
            return 1
        def isatty(self):
            return True
    monkeypatch.setattr(sync_output.sys, "stdin", FakeStream())
    monkeypatch.setattr(sync_output.sys, "stdout", FakeStream())

    reply = sync_output._query_mode_2026(timeout_s=1.0)
    assert reply is not None, "终止符跨边界时不应超时返 None"
    assert "$y" in reply, f"join 后 reply 应含终止符,实际 {reply!r}"
    parsed = sync_output._parse_dectrqm_reply(reply)
    assert parsed is True, (
        f"split-join 后 reply 应被认作 supported,实际 parsed={parsed!r}"
    )


# ───── helpers ─────

def _make_fake_tty() -> io.StringIO:
    s = io.StringIO()
    s.isatty = lambda: True  # type: ignore[assignment]
    return s


def _patch_fake_tty(monkeypatch) -> None:
    """Internal documentation."""
    fake_in = io.StringIO()
    fake_in.isatty = lambda: True  # type: ignore[assignment]
    monkeypatch.setattr(sync_output.sys, "stdin", fake_in)