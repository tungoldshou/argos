"""DECSET 2026 (Synchronized Output) 包装层单元测试。

终端流式输出防撕裂协议:xterm/Kitty/iTerm2/Ghostty 等支持 CSI ?2026 h/l,
让终端在收到 ESU 前不渲染,避免肉眼可见的"逐行蹦出"。
本模块做能力探测 + 安全包装,降级路径对老终端透明。

覆盖:
- 协议常量正确性
- probe 在非 TTY / 超时 / 不支持 / 支持四条路径
- probe 缓存(#4 perf fix):同进程多次调用只探测一次
- sync_batch 在启用 / 禁用 / 异常 / 空块 / 多次写入各种情况下的行为
- sync_batch BSU/ESU 安全契约(#1 fix):BSU write/flush 失败时尽力恢复 ESU
- _query_mode_2026 chunk join(#2 fix):$y 跨 read 边界能正确终止 + EOF 安全

真 TTY 路径不测(需要 ptys/真终端),靠 live smoke 验证。
"""
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
    """每个测试前后清 probe 缓存,防止跨测试污染。

    probe_sync_output 是 per-process 缓存(module-level 状态),不像 monkeypatch
    会自动还原。如果不清,前一个测试的 True 会污染下一个的 False 断言。
    """
    clear_probe_cache()
    yield
    clear_probe_cache()


# ───── 协议常量 ─────

def test_csi_bsu_matches_xterm_extension():
    """CSI ?2026 h 是 xterm-ext 同步输出协议原文(必须严格匹配)。"""
    assert CSI_BSU == "\x1b[?2026h"


def test_csi_esu_matches_xterm_extension():
    """CSI ?2026 l 是对应的关闭序列。"""
    assert CSI_ESU == "\x1b[?2026l"


# ───── probe_sync_output ─────

def test_probe_returns_false_when_stream_not_tty():
    """非 TTY 流(StringIO/文件/pipe)→ False,避免给 head/日志加无意义转义。"""
    assert probe_sync_output(stream=io.StringIO()) is False


def test_probe_returns_false_when_stdin_not_tty(monkeypatch):
    """stdout 是 TTY 但 stdin 不是 → False(读不到回复)。"""
    fake_out = _make_fake_tty()
    fake_in = io.StringIO()  # 默认 isatty=False
    monkeypatch.setattr(sync_output.sys, "stdin", fake_in)
    assert probe_sync_output(stream=fake_out) is False


def test_probe_returns_false_on_query_timeout(monkeypatch):
    """_query_mode_2026 返回 None(超时)→ False(降级,不假装支持)。"""
    monkeypatch.setattr(sync_output, "_query_mode_2026", lambda _t: None)
    _patch_fake_tty(monkeypatch)
    assert probe_sync_output(stream=_make_fake_tty()) is False


def test_probe_returns_true_for_ps_1(monkeypatch):
    """DECRQM 回复 Ps=1 (currently set) → True。"""
    monkeypatch.setattr(
        sync_output, "_query_mode_2026",
        lambda _t: "\x1b[?2026;1$y",
    )
    _patch_fake_tty(monkeypatch)
    assert probe_sync_output(stream=_make_fake_tty()) is True


def test_probe_returns_true_for_ps_2(monkeypatch):
    """DECRQM 回复 Ps=2 (permanently reset) → True。"""
    monkeypatch.setattr(
        sync_output, "_query_mode_2026",
        lambda _t: "\x1b[?2026;2$y",
    )
    _patch_fake_tty(monkeypatch)
    assert probe_sync_output(stream=_make_fake_tty()) is True


def test_probe_returns_false_for_ps_0(monkeypatch):
    """DECRQM 回复 Ps=0 (not recognized) → False。"""
    monkeypatch.setattr(
        sync_output, "_query_mode_2026",
        lambda _t: "\x1b[?2026;0$y",
    )
    _patch_fake_tty(monkeypatch)
    assert probe_sync_output(stream=_make_fake_tty()) is False


def test_probe_returns_false_for_garbage_reply(monkeypatch):
    """回复里没合法模式 2026 DECRQM 序列 → False(不假装)。"""
    monkeypatch.setattr(
        sync_output, "_query_mode_2026",
        lambda _t: "garbage\x1b[?2027;2$y",  # 错的模式号
    )
    _patch_fake_tty(monkeypatch)
    assert probe_sync_output(stream=_make_fake_tty()) is False


def test_probe_returns_false_for_empty_reply(monkeypatch):
    """空字符串回复 → False(None 路径同上)。"""
    monkeypatch.setattr(sync_output, "_query_mode_2026", lambda _t: "")
    _patch_fake_tty(monkeypatch)
    assert probe_sync_output(stream=_make_fake_tty()) is False


def test_probe_returns_false_when_reply_omits_numeric(monkeypatch):
    """某些终端省略数字字段(裸 '$y')→ False(无法验证状态,保守降级)。"""
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
    """stream=None → 走 sys.stdout;test 环境 sys.stdout 被 pytest 替换,非 TTY → False,不崩。"""
    assert probe_sync_output(stream=None) is False


def test_probe_returns_false_when_isatty_raises():
    """isatty() 抛 AttributeError → False(边界:某些被 wrap 过的流可能如此)。"""
    class FlakyStream:
        def isatty(self):
            raise AttributeError("flaky")
        def write(self, _s): pass  # noqa: ARG002
        def flush(self): pass  # noqa: ARG002
    assert probe_sync_output(stream=FlakyStream()) is False


# ───── _is_tty 直接边界 ─────

def test_is_tty_returns_false_for_none():
    """stream=None 直接 False,不调用 .isatty()(防御 NoneType)。"""
    assert sync_output._is_tty(None) is False  # noqa: SLF001


def test_is_tty_returns_false_when_isatty_raises_attribute_error():
    """isatty 抛 AttributeError → False。"""
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
    """isatty 抛 ValueError(常见:已关闭的 file wrapper / 在 closed file 上调用)→ False。
    跟 AttributeError 路径一样兜底,代码用 except (AttributeError, ValueError)。"""
    class ClosedFileLike:
        def isatty(self):
            raise ValueError("I/O operation on closed file")
        def write(self, _s): pass  # noqa: ARG002
        def flush(self): pass  # noqa: ARG002
    assert sync_output._is_tty(ClosedFileLike()) is False  # noqa: SLF001


# ───── probe_sync_output 缓存(#4 perf fix)─────

def test_probe_caches_result_across_calls(monkeypatch):
    """第二次 probe_sync_output 不再调 _query_mode_2026(per-process 缓存)。
    真实 termios dance 50ms+ syscalls,per-chunk 调用是性能坑。"""
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
    """clear_probe_cache() 后下次 probe 重新探测 —— 用于切终端 / 长会话状态变化。"""
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
    """缓存 False(不支持)也生效 —— 多次调用 probe 不支持终端不应反复发 DECRQM 查询。"""
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
    """非 TTY 短路不应污染缓存 —— False 必须来自 isatty 检查而不是缓存命中。"""
    call_count = {"n": 0}

    def fake_query(_t):
        call_count["n"] += 1
        return "\x1b[?2026;2$y"

    _patch_fake_tty(monkeypatch)
    monkeypatch.setattr(sync_output, "_query_mode_2026", fake_query)

    # 第一次:非 TTY 路径,不查 _query_mode_2026,也不写缓存
    r1 = probe_sync_output(stream=io.StringIO())  # StringIO 默认 isatty=False
    assert r1 is False
    assert call_count["n"] == 0, "非 TTY 短路应直接返,不应触发 probe"

    # 第二次:真 TTY,正常探测(缓存应空)
    r2 = probe_sync_output(stream=_make_fake_tty())
    assert r2 is True
    assert call_count["n"] == 1


# ───── sync_batch ─────

def test_sync_batch_emits_brackets_when_enabled():
    """enabled=True → 进入写 BSU,退出写 ESU,中间 write 原样透传。"""
    buf = io.StringIO()
    with sync_batch(buf, enabled=True):
        buf.write("hello")
    assert buf.getvalue() == CSI_BSU + "hello" + CSI_ESU


def test_sync_batch_is_noop_when_disabled():
    """enabled=False → 完全不插入 BSU/ESU(老终端透明降级)。"""
    buf = io.StringIO()
    with sync_batch(buf, enabled=False):
        buf.write("hello")
    assert buf.getvalue() == "hello"


def test_sync_batch_emits_esu_on_exception():
    """异常路径仍发 ESU(避免终端永远挂着同步模式导致屏幕死锁)。"""
    buf = io.StringIO()
    with pytest.raises(RuntimeError, match="boom"):
        with sync_batch(buf, enabled=True):
            buf.write("partial")
            raise RuntimeError("boom")
    assert buf.getvalue() == CSI_BSU + "partial" + CSI_ESU


def test_sync_batch_empty_block_still_emits_esu():
    """空块(没 write)也要发 ESU,避免 BSU 挂起。"""
    buf = io.StringIO()
    with sync_batch(buf, enabled=True):
        pass
    assert buf.getvalue() == CSI_BSU + CSI_ESU


def test_sync_batch_passes_through_multiple_writes():
    """with 块内多次 write 原样写入,不做行缓冲或合并。"""
    buf = io.StringIO()
    with sync_batch(buf, enabled=True):
        buf.write("a")
        buf.write("b")
        buf.write("\n")
        buf.write("c")
    assert buf.getvalue() == CSI_BSU + "ab\nc" + CSI_ESU


def test_sync_batch_none_auto_probes_unsupported(monkeypatch):
    """enabled=None → 现场 probe,probe=False 时不发 BSU/ESU。"""
    monkeypatch.setattr(sync_output, "probe_sync_output", lambda _s: False)
    buf = io.StringIO()
    with sync_batch(buf):
        buf.write("hello")
    assert buf.getvalue() == "hello"


def test_sync_batch_none_auto_probes_supported(monkeypatch):
    """enabled=None 且 probe=True → 正常发 BSU/ESU。"""
    monkeypatch.setattr(sync_output, "probe_sync_output", lambda _s: True)
    buf = io.StringIO()
    with sync_batch(buf):
        buf.write("hello")
    assert buf.getvalue() == CSI_BSU + "hello" + CSI_ESU


def test_sync_batch_does_not_probe_when_enabled_explicit(monkeypatch):
    """显式 enabled=True 时不应调用 probe(避免昂贵 termios 调用)。"""
    called = {"count": 0}
    def fake_probe(_s):
        called["count"] += 1
        return True
    monkeypatch.setattr(sync_output, "probe_sync_output", fake_probe)
    buf = io.StringIO()
    with sync_batch(buf, enabled=True):
        buf.write("x")
    assert called["count"] == 0, "显式 enabled 时不应现场探测"


# ───── sync_batch 错误恢复(BSU 写出后 flush 抛异常)─────

def test_sync_batch_emits_esu_recovery_when_bsu_flush_fails():
    """BSU write/flush 阶段抛异常 → 仍尽力发出 ESU,避免终端永久挂同步模式。
    docstring 契约:'任何情况下都保证 ESU 被发出'——这条测试守住它。"""
    written: list[str] = []
    state = {"flush_count": 0}

    class FlakyStream:
        def write(self, s):
            written.append(s)
        def flush(self):
            state["flush_count"] += 1
            if state["flush_count"] == 1:
                # BSU 写出后 flush 失败:模拟磁盘满 / pipe 断
                raise OSError("disk full on BSU flush")

    buf = FlakyStream()
    with pytest.raises(OSError, match="disk full"):
        with sync_batch(buf, enabled=True):
            pass

    # BSU 已被尝试发出,ESU 作为恢复动作紧随其后
    assert CSI_BSU in written, "BSU 应该已经被尝试写出"
    assert CSI_ESU in written, "BSU flush 失败时仍应尽力发 ESU 恢复"
    assert written.index(CSI_BSU) < written.index(CSI_ESU), (
        "ESU 必须在 BSU 之后(恢复路径)"
    )


def test_sync_batch_emits_esu_recovery_when_bsu_write_fails():
    """BSU write 本身抛异常(比如断 pipe)→ 仍尽力发 ESU。"""
    written: list[str] = []
    state = {"write_count": 0}

    class FlakyStream:
        def write(self, s):
            state["write_count"] += 1
            if state["write_count"] == 1:
                raise OSError("broken pipe on BSU write")
            written.append(s)  # 第二次(ESU)成功才记入
        def flush(self):
            pass

    buf = FlakyStream()
    with pytest.raises(OSError, match="broken pipe"):
        with sync_batch(buf, enabled=True):
            pass

    # 即使 BSU write 失败,ESU 仍要尝试(可能终端已经收到部分 BSU)
    assert CSI_ESU in written, "BSU write 失败后仍应尝试发 ESU"
    assert state["write_count"] >= 2, "应该至少调用过 2 次 write(BSU+ESU)"


def test_sync_batch_recovery_silently_swallows_esu_failures():
    """ESU 恢复动作本身也失败时(终端彻底没救了)→ 静默吞掉,不抛新异常覆盖原异常。"""
    state = {"flush_count": 0}

    class DoomedStream:
        def write(self, _s):
            pass
        def flush(self):
            state["flush_count"] += 1
            if state["flush_count"] == 1:
                raise OSError("BSU flush failed")
            # ESU flush 也失败:不抛新异常吞掉
            raise OSError("ESU flush also failed")

    buf = DoomedStream()
    # 原异常(BSU flush)应该传出,而不是被 ESU 失败覆盖
    with pytest.raises(OSError, match="BSU flush failed"):
        with sync_batch(buf, enabled=True):
            pass


# ───── _query_mode_2026 chunk join($y 跨 read 边界)─────

def test_query_mode_2026_joins_split_terminator(monkeypatch):
    """DECRQM 回复的 '$y' 终止符被拆到两个 os.read() 时,probe 必须 join 后判终止,
    不能因为当前 chunk 不含 '$y' 就死循环等 timeout。
    """
    # 模拟 termios/tty(都是 no-op,只要不抛)。FakeTermios 必须暴露 TCSADRAIN
    # 常量和 error 异常类(finally 块 tcsetattr 会引用)。
    class FakeTermiosError(Exception):
        pass

    class FakeTermios:
        TCSADRAIN = 1  # 常量,实现不关心值
        error = FakeTermiosError

        @staticmethod
        def tcgetattr(_fd):
            return [0] * 20  # 任意 list-like

        @staticmethod
        def tcsetattr(_fd, _when, _settings):
            pass

    class FakeTty:
        @staticmethod
        def setraw(_fd):
            pass

    monkeypatch.setattr(sync_output, "termios", FakeTermios)
    monkeypatch.setattr(sync_output, "tty", FakeTty)

    # 关键 mock:drain loop(timeout=0)立即退出,不能消费 chunks;
    # 主 loop 才应该拿到数据。
    chunks_data = [
        b"\x1b[?2026;2$",  # 第一个 chunk:没有 '$y'
        b"y",              # 第二个 chunk:'$y' 被拆了
    ]
    state = {"read_idx": 0}

    def fake_select(rlist, wlist, xlist, timeout):
        # drain loop 用 timeout=0 调用 → 立刻返空,跳过排空
        if timeout == 0:
            return ([], [], [])
        # 主 loop:有数据就返 ready,排空后返空(触发 EOF break)
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

    # 假装 stdin/stdout 都是 TTY(跳过外层 isatty 短路)
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
    # 进一步:reply 应能被 _parse_dectrqm_reply 正确解出 → True
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
    """让 probe_sync_output 走 _query_mode_2026 路径(不卡在 isatty 检查)。"""
    fake_in = io.StringIO()
    fake_in.isatty = lambda: True  # type: ignore[assignment]
    monkeypatch.setattr(sync_output.sys, "stdin", fake_in)