from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from argos.tui.sync_output import probe_sync_output, sync_batch


def stream_demo(
    *,
    chunks: int,
    chunk_size: int,
    delay_ms: int,
    use_sync: bool | None,
) -> None:
    mode_label = {True: "SYNC ON", False: "SYNC OFF", None: "AUTO(probe)"}[use_sync]
    header = f"─── {mode_label} · {chunks} chunks × {chunk_size} chars · {delay_ms}ms delay ───\n"
    sys.stdout.write(header)
    sys.stdout.flush()

    t0 = time.perf_counter()
    with sync_batch(sys.stdout, enabled=use_sync):
        for i in range(chunks):
            chunk = f"[{i:04d}]".ljust(chunk_size)[:chunk_size]
            sys.stdout.write(chunk)
            sys.stdout.flush()
            if delay_ms > 0:
                time.sleep(delay_ms / 1000.0)
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