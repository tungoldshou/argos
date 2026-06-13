"""`python -m argos.daemon` 入口(spec §2.10 + D13)。

`argos daemon` 子命令也走这个入口。
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import os
import signal
import sys
from pathlib import Path

log = logging.getLogger(__name__)


def _default_runs_dir() -> Path:
    return Path.home() / ".argos" / "runs"


def _default_index_path() -> Path:
    return Path.home() / ".argos" / "runs" / "index.json"


def _default_socket_path() -> Path:
    return Path.home() / ".argos" / "daemon.sock"


def _default_pid_path() -> Path:
    return Path.home() / ".argos" / "daemon.pid"


async def _serve(args: argparse.Namespace) -> int:
    from argos.daemon.manager import RunManager
    from argos.daemon.pidfile import write_pid, remove as remove_pid
    from argos.daemon.server import DaemonHTTPServer
    from argos.daemon.socket import check_socket_available, ensure_socket_mode
    from argos.daemon.supervision import graceful_shutdown, install_signal_handlers

    runs_dir = Path(args.runs_dir).expanduser()
    index_path = Path(args.index_path).expanduser()
    socket_path = Path(args.socket_path).expanduser()
    pid_path = Path(args.pid_path).expanduser()

    runs_dir.mkdir(parents=True, exist_ok=True)
    index_path.parent.mkdir(parents=True, exist_ok=True)

    # 检查 socket 占用
    try:
        check_socket_available(socket_path)
    except RuntimeError as e:
        print(f"[daemon] {e}", file=sys.stderr)
        return 1

    # P1 通电:装配真实组件 + loop_factory ──────────────────────────────
    # 无 worker key → loop_factory=_NO_KEY 哨兵,daemon 仍能启动;create_run 明确拒绝并说明原因。
    from argos.daemon.server import _NO_KEY
    loop_factory = _NO_KEY  # 默认无 key 状态
    components = None
    try:
        from argos.app_factory import build_components, build_loop_factory
        components = build_components()
        loop_factory = build_loop_factory(components)
        log.info("daemon: AgentLoop factory 装配完成(model=%s)", components.config.model_tier)
    except RuntimeError as e:
        # 诚实降级:无 key → daemon 起得来,但 create_run 会明确拒绝(_NO_KEY 哨兵)
        print(f"[daemon] 警告:无法装配 AgentLoop({e});daemon 以无 key 模式启动,create_run 将拒绝。",
              file=sys.stderr)
        log.warning("daemon: loop_factory 装配失败: %s", e)
    except Exception as e:  # noqa: BLE001
        print(f"[daemon] 警告:装配异常({e});daemon 以无 key 模式启动。", file=sys.stderr)
        log.warning("daemon: loop_factory 装配异常: %s", e)

    manager = RunManager(runs_dir=runs_dir, index_path=index_path)
    # 启动恢复
    recovered = manager.recover()
    if recovered:
        log.info("daemon: recovered %d runs: %s", len(recovered), recovered)

    # P5b §9 自治面：conductor supervisor（tick loop 后台协程）
    # 广播函数：向 _conductor 虚拟 run_id 的 SSE 扇出通道投事件
    from argos.daemon.conductor_supervisor import ConductorSupervisor, CONDUCTOR_RUN_ID
    conductor_orders_dir = Path.home() / ".argos" / "conductor"

    async def _conductor_broadcast(ev_dict: dict) -> None:
        """把 conductor 事件存入 _conductor 流并扇出到 SSE 订阅者。"""
        manager.store.append(CONDUCTOR_RUN_ID, ev_dict)
        await manager.fanout(CONDUCTOR_RUN_ID, ev_dict)

    conductor_supervisor = ConductorSupervisor(
        orders_dir=conductor_orders_dir,
        tick_interval=float(os.environ.get("ARGOS_CONDUCTOR_TICK_INTERVAL", "30")),
        broadcast_fn=_conductor_broadcast,
    )

    # P3b §6 行为账本存储(全局单例,所有 run 共享同一个目录)
    from argos.ledger.store import LedgerStore
    ledger_store = LedgerStore()

    server = DaemonHTTPServer(
        manager=manager,
        socket_path=socket_path,
        # components 路径(优先):per-run 独享 sandbox/gate/broker,并发不串台。
        # 无 components(装配失败)时退回 loop_factory=_NO_KEY 哨兵诚实拒绝。
        components=components,
        loop_factory=loop_factory,
        gate=components.gate if components is not None else None,
        ledger_store=ledger_store,
        conductor_supervisor=conductor_supervisor,
    )
    await server.start()
    # P5b §9:启动 conductor tick 后台协程
    conductor_supervisor.start()

    # 写 PID
    write_pid(pid_path, os.getpid())
    ensure_socket_mode(socket_path)

    print(f"[daemon] started, socket={socket_path}, pid={os.getpid()}")

    # 信号处理
    loop = asyncio.get_event_loop()
    shutdown_event = asyncio.Event()

    def _on_signal() -> None:
        if not shutdown_event.is_set():
            log.info("daemon: signal received, scheduling shutdown")
            shutdown_event.set()

    install_signal_handlers(loop, _on_signal)

    try:
        await shutdown_event.wait()
    finally:
        # P5b §9:先停 conductor tick(干净取消,不留孤儿任务)
        try:
            await conductor_supervisor.stop()
        except Exception as e:  # noqa: BLE001
            log.warning("daemon: conductor_supervisor.stop() failed: %s", e)
        await graceful_shutdown(manager, server, socket_path)
        remove_pid(pid_path)
        # 清理 AppComponents(关闭 sandbox/store/browser/mcp 子进程)
        if components is not None:
            try:
                components.close()
            except Exception as e:  # noqa: BLE001
                log.warning("daemon: components.close() failed: %s", e)
    return 0


def main() -> int:
    p = argparse.ArgumentParser(
        prog="python -m argos.daemon",
        description="Argos background daemon (long-running tasks)",
    )
    p.add_argument("--detach", action="store_true", help="detach from controlling tty")
    p.add_argument("--runs-dir", default=str(_default_runs_dir()))
    p.add_argument("--index-path", default=str(_default_index_path()))
    p.add_argument("--socket-path", default=str(_default_socket_path()))
    p.add_argument("--pid-path", default=str(_default_pid_path()))
    p.add_argument("--log-level", default="info",
                   choices=["debug", "info", "warning", "error"])
    args = p.parse_args()

    logging.basicConfig(
        level=getattr(logging, args.log_level.upper()),
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )
    return asyncio.run(_serve(args))


if __name__ == "__main__":
    sys.exit(main())
