"""DECSET 2026 (Synchronized Output) 包装层,PoC。

终端流式输出防撕裂协议:xterm / Kitty / iTerm2 / Ghostty 等支持
CSI ?2026 h/l。包住大块写入,让终端在收到 ESU 前不渲染,避免肉眼可见
的"逐行蹦出"。不支持的终端 → 透明 no-op。

参考资料:
- https://gist.github.com/christianparpart/d8a62cc1ab658a22956e611b958b8b9d
- xterm 扩展文档:Synchronized updates
"""
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

# Mode 2026 — Synchronized Output(DEC 私有模式,2026 号)。
CSI_BSU = "\x1b[?2026h"   # Begin Synchronized Update
CSI_ESU = "\x1b[?2026l"   # End Synchronized Update
CSI_QUERY = "\x1b[?2026$p"  # DECRQM 查询(CSI ? Pd $ p)

# DECRQM 回复:CSI ?2026 ; Ps $ y
# Ps = 0 not recognized
# Ps = 1 recognized, currently set
# Ps = 2 recognized, permanently reset
# Ps = 3 recognized, not permanently reset
# Ps = 4 not available
_RE_DECTRQM = re.compile(r"\x1b\[\?2026(?:\s*;\s*([0-4]))?\$y")
_SUPPORTED_PS = frozenset({1, 2, 3})


def _is_tty(stream: TextIO | None) -> bool:
    """兼容 None / 非 file 对象 / isatty 抛异常的边界情况。"""
    if stream is None:
        return False
    try:
        return bool(stream.isatty())
    except (AttributeError, ValueError):
        return False


def _parse_dectrqm_reply(reply: str) -> bool | None:
    """解析 DECRQM 模式 2026 的回复。

    Returns:
        True — 终端识别此模式
        False — 终端明确表示不识别
        None — 没收到合法回复(乱码/超时)
    """
    if not reply:
        return None
    m = _RE_DECTRQM.search(reply)
    if not m:
        return None
    ps_str = m.group(1)
    if ps_str is None:
        # 某些终端省略数字字段 → 保守认作无法验证,不假装支持
        return False
    # 正则限定 [0-4],所以只需检查是否在 {1, 2, 3}。0 / 4 即不支持。
    return int(ps_str) in _SUPPORTED_PS


def _query_mode_2026(timeout_s: float) -> str | None:
    """在真 TTY 上发 DECRQM 查询并读回复。

    仅当 stdin + stdout 均为 TTY 时安全。调用方需先做 isatty() 预检。

    Returns:
        累积的回复字符串(含可能的混入字节),或 None(超时 / 读写失败)。
    """
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
        # raw 模式:关 echo / canonical,确保 read 不被行缓冲截断
        tty.setraw(fd_in)

        # 排空残留输入(避免读到陈旧字节误判)
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
                break  # EOF(罕见但安全:pipe 关闭 / TTY detach)
            reply_parts.append(chunk)
            # 跨 read 边界 join 后再判终止符(split-safe):DECRQM 回复只有 16 字节左右,
            # "$y" 可能被拆成两个 chunk。检查累计 reply 而不是当前 chunk。
            if "$y" in "".join(reply_parts):
                break

        return "".join(reply_parts) or None
    finally:
        # 无论发生什么,都要还原终端设置 —— 否则用户后续按键乱码
        try:
            termios.tcsetattr(fd_in, termios.TCSADRAIN, old_settings)
        except (termios.error, OSError):
            pass


# Per-process 缓存:`None` = 还没探测过;`True` / `False` = 已探测。
# 设计成 module-global 而非函数 default arg:方便 clear_probe_cache() 显式清。
_probe_cache: bool | None = None


def probe_sync_output(
    stream: TextIO | None = None,
    timeout_s: float = 0.05,
) -> bool:
    """探测 stream 对应的终端是否支持 DECSET 2026 同步输出协议。

    非 TTY / stdin 不可读 / 查询超时 / 收到 "not recognized" → False(透明降级)。

    **缓存行为**:首次调用做完整 termios dance(~5-10ms syscalls),后续调用返缓存。
    终端能力是 per-process 的,不会因为 stream 参数变化而不同。per-chunk 高频调用
    场景下,缓存避免重复 probe 的 perf 坑(原本每次 ~50ms+ raw mode toggle)。
    切终端 / 状态变化 → 调 `clear_probe_cache()`。

    Args:
        stream: 要写入的目标流。None 时用 sys.stdout(仅用于 isatty 短路判断,
                不影响缓存 key —— 同一进程内 stream 参数变化不触发重探测)。
        timeout_s: 探测超时上限(秒)。过短可能误判不支持。

    Returns:
        True 表示支持同步输出,调用方可放心用 sync_batch(enabled=True)。
    """
    global _probe_cache
    # Cache hit:per-process 同一终端能力,无需重探测。
    if _probe_cache is not None:
        return _probe_cache

    if stream is None:
        stream = sys.stdout
    if not _is_tty(stream):
        return False  # 非 TTY 短路不写缓存(下次真 TTY 调用仍要探测)
    if not _is_tty(sys.stdin):
        return False  # 没 tty stdin 就读不到回复,强降级

    reply = _query_mode_2026(timeout_s)
    if reply is None:
        # 超时:不缓存(下次可能 terminal 状态变了;超时失败值得重试一次)
        return False
    parsed = _parse_dectrqm_reply(reply)
    if parsed is None:
        return False

    # 全局缓存结果(支持 / 不支持都缓存)。terminal 切了再 clear。
    _probe_cache = parsed
    return parsed


def clear_probe_cache() -> None:
    """清掉 probe_sync_output 的缓存,下次调用重新探测。

    场景:用户切换终端(如从 SSH 跳到本地) / 长会话中状态变化 / 测试隔离。
    普通 CLI 一次性的用法不需要调 —— 进程结束缓存自然消失。
    """
    global _probe_cache
    _probe_cache = None


@contextmanager
def sync_batch(
    stream: TextIO,
    enabled: bool | None = None,
) -> Iterator[None]:
    """同步输出一批写入。

    用法::

        with sync_batch(stdout, enabled=True):
            stdout.write("large chunk...")
            stdout.flush()

    - enabled=True:发 BSU / ESU(假定终端支持,调用方负责探测)
    - enabled=False:不插入任何东西,with 块等价于 no-op
    - enabled=None:现场 probe 一次,根据探测结果决定(自动降级)

    任何情况下(包括 with 块内抛异常)都保证 ESU 被发出,避免终端
    永远挂在同步模式里导致屏幕死锁。
    """
    if enabled is None:
        enabled = probe_sync_output(stream)

    if not enabled:
        yield
        return

    # BSU 写出阶段(可能部分或完全失败)包进 try/except,失败时尽力恢复 ESU。
    # 不这样做的话:stream.flush() 在 BSU 写出后抛 OSError(磁盘满 / pipe 断),
    # BSU 已经到终端、ESU 永远不来 → 终端永久挂同步模式,后续输出全部吞掉。
    try:
        stream.write(CSI_BSU)
        stream.flush()
    except Exception:
        # 恢复动作:尽量发 ESU 让终端退出同步模式。ESU 本身失败也吞掉
        # (终端彻底坏掉时不该再覆盖原异常)。
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
            # ESU 失败也吞掉(原异常已设置,新异常不应覆盖)
            pass