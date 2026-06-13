"""Sync output 协议(DECSET 2026)的 A/B 对比 demo。

目的:让真人能在自己终端里直观看到同步输出协议对流式渲染的影响。
不是为了 benchmark(没统计 Δ),只是"看一眼就懂"。

原理:
- 同步输出协议 = xterm / Kitty / iTerm2 / Ghostty 支持的 DECSET 2026
- 模式开启(CSI ?2026 h)后,终端把后续输出攒住不渲染,直到收到关闭(CSI ?2026 l)才一次性显示
- 老终端 / 不支持 → 透明 no-op;支持 → 流式 chunk 一次性"啪"地落屏,无"逐行蹦出"

用法(必须在你自己的真终端里跑):

    uv run python scripts/sync_output_demo.py                 # 默认:auto(现场 probe)
    uv run python scripts/sync_output_demo.py --sync          # 强制开
    uv run python scripts/sync_output_demo.py --no-sync      # 强制关
    uv run python scripts/sync_output_demo.py --chunks 200 --chunk-size 30 --delay-ms 30
                                                          # 调慢,差异更明显

注意:
- 非 TTY(piped)跑不出来效果——必须真终端
- 默认 --delay-ms 30 适合一般终端;SSH 远程 / 老终端建议 --delay-ms 80-100
- 推荐 a/b 步骤:
    1. 跑 --no-sync(看 baseline:逐行蹦出)
    2. 跑 --sync(看同步:整块啪地落)
    3. 跑默认(auto)看 probe 自动判断
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

# 让脚本可以直接 import argos
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from argos.tui.sync_output import probe_sync_output, sync_batch


def stream_demo(
    *,
    chunks: int,
    chunk_size: int,
    delay_ms: int,
    use_sync: bool | None,
) -> None:
    """流 N 个 chunk,每个之间睡 delay_ms 毫秒,模拟 token-by-token 输出。

    use_sync:
        True  → 整批包在 sync_batch(enabled=True),强制走 BSU/ESU
        False → 完全不开(等价 sync_batch(enabled=False))
        None  → sync_batch(enabled=None)现场 probe 决定(auto)
    """
    # 头部标记:本次用什么模式,方便肉眼区分两次跑
    mode_label = {True: "SYNC ON", False: "SYNC OFF", None: "AUTO(probe)"}[use_sync]
    header = f"─── {mode_label} · {chunks} chunks × {chunk_size} chars · {delay_ms}ms delay ───\n"
    sys.stdout.write(header)
    sys.stdout.flush()

    t0 = time.perf_counter()
    with sync_batch(sys.stdout, enabled=use_sync):
        for i in range(chunks):
            # 把 chunk 序号混进 payload,这样能看清"是否分多次落屏"
            chunk = f"[{i:04d}]".ljust(chunk_size)[:chunk_size]
            sys.stdout.write(chunk)
            sys.stdout.flush()
            if delay_ms > 0:
                time.sleep(delay_ms / 1000.0)
    # flush + newline 在 with 外,确保 ESU 之后再换行
    sys.stdout.write("\n")
    sys.stdout.flush()

    elapsed = time.perf_counter() - t0
    sys.stdout.write(
        f"─── done in {elapsed * 1000:.0f}ms "
        f"(should ≈ chunks × delay_ms = {chunks * delay_ms}ms) ───\n\n"
    )
    sys.stdout.flush()


def main() -> int:
    p = argparse.ArgumentParser(
        description="DECSET 2026 sync output A/B 对比 demo。",
    )
    p.add_argument(
        "--sync", dest="use_sync", action="store_const", const=True, default=None,
        help="强制开 sync_batch(跳过 probe)",
    )
    p.add_argument(
        "--no-sync", dest="use_sync", action="store_const", const=False,
        help="强制关 sync_batch(等价裸写)",
    )
    p.add_argument(
        "--chunks", type=int, default=80,
        help="写多少个 chunk(默认 80,适合一般终端)",
    )
    p.add_argument(
        "--chunk-size", type=int, default=24,
        help="每个 chunk 多少字符(默认 24)",
    )
    p.add_argument(
        "--delay-ms", type=int, default=30,
        help="chunk 间延迟 ms(默认 30;老终端/SSH 建议 80-100)",
    )
    p.add_argument(
        "--probe", action="store_true",
        help="只探测一次终端是否支持 mode 2026 然后退出(不做流)",
    )
    args = p.parse_args()

    if args.probe:
        supported = probe_sync_output()
        is_tty = sys.stdout.isatty()
        sys.stdout.write(
            f"isatty={is_tty}  sync_output(mode 2026) supported={supported}\n"
        )
        sys.stdout.flush()
        return 0

    if not sys.stdout.isatty():
        sys.stderr.write(
            "[demo] WARNING: stdout 不是 TTY(被 piped)。\n"
            "        在 pipe 模式 sync_batch 透明 no-op,看不到效果。\n"
            "        请直接跑(不要 `| cat` / `| tee`)以获得真实视觉对比。\n"
        )

    stream_demo(
        chunks=args.chunks,
        chunk_size=args.chunk_size,
        delay_ms=args.delay_ms,
        use_sync=args.use_sync,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())