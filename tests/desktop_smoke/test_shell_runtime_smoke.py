"""A 轨:桌面壳运行时冒烟测试 — 专杀"植物人前端"类 bug。

背景
----
bug5 = 前端 JS 从未执行:cargo/tsc 双绿但窗口是死的。编译期冒烟看不出来,
必须起真进程观测运行时行为。

核心思路:【daemon 侧 session 创建 = JS 存活铁证】
  - JS 死了 → initConnection() 永远不执行 → 无人调 acp_create_session
  - acp_create_session 调 Rust bridge → Rust 发 POST /sessions 到 DaemonHTTPServer
  - DaemonHTTPServer.sessions 出现 ≥1 条 session = JS 在跑

窗口会闪一下:这是真窗口冒烟的代价。测试在 darwin GUI 会话里跑,
必须有 WindowServer 才能起 Tauri 窗口。

使用方法:
  uv run pytest tests/desktop_smoke/ -m "slow" -q --no-cov -x
"""
from __future__ import annotations

import asyncio
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import pytest

# ── 编译产物路径 ──────────────────────────────────────────────────────────────

_REPO_ROOT = Path(__file__).resolve().parents[2]
_SHELL_TAURI = _REPO_ROOT / "desktop" / "shell" / "src-tauri"
_BINARY = _SHELL_TAURI / "target" / "debug" / "argos-shell"
_SHELL_TS_DIR = _REPO_ROOT / "desktop" / "shell"


# ── Skipif 守卫 ───────────────────────────────────────────────────────────────

def _has_window_server() -> bool:
    """检测当前是否有图形化 GUI 会话(macOS WindowServer)。

    Tauri 窗口必须有 WindowServer 才能弹出。CI headless 环境没有 WindowServer,
    诚实 skip 而非假绿。
    """
    result = subprocess.run(
        ["pgrep", "-x", "WindowServer"],
        capture_output=True,
        timeout=3,
    )
    return result.returncode == 0


_SKIP_NOT_DARWIN = pytest.mark.skipif(
    sys.platform != "darwin",
    reason="桌面壳冒烟测试仅适用于 macOS(Tauri + Seatbelt 平台限定)",
)
_SKIP_NO_CARGO = pytest.mark.skipif(
    shutil.which("cargo") is None,
    reason="cargo 不在 PATH,无法构建 Rust 产物",
)
_SKIP_NO_NODE = pytest.mark.skipif(
    shutil.which("node") is None,
    reason="node 不在 PATH,无法运行 tsc 编译 TypeScript",
)
_SKIP_NO_GUI = pytest.mark.skipif(
    sys.platform == "darwin" and not _has_window_server(),
    reason="无 WindowServer GUI 会话(headless CI?),Tauri 窗口无法启动",
)


# ── DaemonHTTPServer in-process 包装 ──────────────────────────────────────────

class _InProcessDaemon:
    """在测试进程内启动一个 DaemonHTTPServer,绑定到临时 Unix socket。

    session_timeout_s=5 让 session 快速过期,避免测试结束后积累孤儿 session。
    """

    def __init__(self, socket_path: Path) -> None:
        self._socket_path = socket_path
        self._loop: asyncio.AbstractEventLoop | None = None
        self._server = None
        self._thread = None

    # -- public API -----------------------------------------------------------

    @property
    def sessions(self):
        """返回 SessionRegistry._sessions dict(同步读,字典原子读)。"""
        if self._server is None:
            return {}
        return self._server.sessions._sessions

    def start(self) -> None:
        """在后台线程启动独立事件循环 + 服务器。"""
        import threading

        self._loop = asyncio.new_event_loop()
        ready = threading.Event()
        self._thread = threading.Thread(target=self._run, args=(ready,), daemon=True)
        self._thread.start()
        if not ready.wait(timeout=5.0):
            raise RuntimeError("in-process DaemonHTTPServer 启动超时(5s)")

    def stop(self) -> None:
        """关闭服务器,停止事件循环。"""
        if self._loop is None:
            return
        future = asyncio.run_coroutine_threadsafe(self._shutdown(), self._loop)
        try:
            future.result(timeout=5.0)
        except Exception:
            pass
        self._loop.call_soon_threadsafe(self._loop.stop)
        if self._thread is not None:
            self._thread.join(timeout=5.0)

    # -- internals ------------------------------------------------------------

    def _run(self, ready) -> None:
        asyncio.set_event_loop(self._loop)
        self._loop.run_until_complete(self._start(ready))
        self._loop.run_forever()

    async def _start(self, ready) -> None:
        from argos_agent.daemon.manager import RunManager
        from argos_agent.daemon.server import DaemonHTTPServer

        runs_dir = self._socket_path.parent / "runs"
        runs_dir.mkdir(parents=True, exist_ok=True)
        index_path = self._socket_path.parent / "index.json"

        manager = RunManager(runs_dir=runs_dir, index_path=index_path)
        self._server = DaemonHTTPServer(
            manager=manager,
            socket_path=self._socket_path,
            session_timeout_s=5.0,
            # loop_factory=None → 元数据模式(无 API key,无 worker);
            # create_session 不需要 key,这是我们测的唯一端点。
        )
        await self._server.start()
        ready.set()  # 通知主线程服务器已就绪

    async def _shutdown(self) -> None:
        if self._server is not None:
            await self._server.stop()


# ── 测试本体 ──────────────────────────────────────────────────────────────────

@pytest.mark.slow
@pytest.mark.xdist_group(name="desktop-shell")
@_SKIP_NOT_DARWIN
@_SKIP_NO_CARGO
@_SKIP_NO_NODE
@_SKIP_NO_GUI
def test_shell_runtime_smoke():
    """桌面壳运行时冒烟:JS 活着 → session 创建铁证 + 心跳前移(bug4 回归钉)。

    端到端链路:
      1. 起 in-process DaemonHTTPServer(tmp socket)
      2. 用 ARGOS_DAEMON_SOCKET 环境变量把 argos-shell binary 指向该 socket
      3. Tauri 窗口弹出 → JS 执行 initConnection() → acp_create_session Rust IPC
      4. Rust bridge 向 DaemonHTTPServer POST /sessions
      5. server.sessions 出现 ≥1 条 → 断言1:JS 活着
      6. 随后 last_seen 前移(心跳) → 断言2:bug4 回归钉

    注:窗口会闪一下,这是真窗口冒烟的代价。
    """
    # ── 步骤1:构建产物 ────────────────────────────────────────────────────────

    # tsc 编译(desktop/shell TypeScript)
    tsc_result = subprocess.run(
        ["npx", "tsc", "--noEmit", "false"],
        cwd=str(_SHELL_TS_DIR),
        capture_output=True,
        text=True,
        timeout=60,
    )
    if tsc_result.returncode != 0:
        pytest.fail(
            f"tsc 编译失败(构建烂了就是红,不 skip):\n"
            f"stdout: {tsc_result.stdout[-1000:]}\n"
            f"stderr: {tsc_result.stderr[-1000:]}"
        )

    # cargo build
    cargo_result = subprocess.run(
        ["cargo", "build"],
        cwd=str(_SHELL_TAURI),
        capture_output=True,
        text=True,
        timeout=120,
    )
    if cargo_result.returncode != 0:
        pytest.fail(
            f"cargo build 失败(构建烂了就是红,不 skip):\n"
            f"stdout: {cargo_result.stdout[-1000:]}\n"
            f"stderr: {cargo_result.stderr[-1000:]}"
        )

    if not _BINARY.exists():
        pytest.fail(f"构建产物不存在:{_BINARY}")

    # ── 步骤2:起 in-process daemon ─────────────────────────────────────────

    with tempfile.TemporaryDirectory(prefix="argos-desktop-smoke-") as tmpdir:
        socket_path = Path(tmpdir) / "daemon.sock"
        daemon = _InProcessDaemon(socket_path)
        proc: subprocess.Popen | None = None

        try:
            daemon.start()

            # ── 步骤3:subprocess 启动 argos-shell,env 指向 tmp socket ─────

            env = os.environ.copy()
            env["ARGOS_DAEMON_SOCKET"] = str(socket_path)
            # 防止壳连接到真实 daemon 作双保险
            env.pop("ARGOS_DAEMON_SOCK", None)

            proc = subprocess.Popen(
                [str(_BINARY)],
                env=env,
                cwd=str(_REPO_ROOT),
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
            )

            # ── 断言1:≤20s 内 sessions 出现 ≥1 条(JS 存活铁证) ──────────

            _WAIT_SESSION_S = 20.0
            _POLL_INTERVAL_S = 0.3

            deadline = time.monotonic() + _WAIT_SESSION_S
            session_appeared = False
            while time.monotonic() < deadline:
                sessions = daemon.sessions
                if sessions:
                    session_appeared = True
                    break
                # 检查进程是否已提前退出
                if proc.poll() is not None:
                    stderr_out = proc.stderr.read().decode("utf-8", errors="replace")
                    pytest.fail(
                        f"argos-shell 提前退出(returncode={proc.returncode});\n"
                        f"stderr: {stderr_out[-800:]}"
                    )
                time.sleep(_POLL_INTERVAL_S)

            if not session_appeared:
                stderr_peek = b""
                try:
                    # 非阻塞读部分 stderr
                    import select as _select
                    rlist, _, _ = _select.select([proc.stderr], [], [], 0.1)
                    if rlist:
                        stderr_peek = proc.stderr.read(800)
                except Exception:
                    pass
                pytest.fail(
                    f"断言1失败:{_WAIT_SESSION_S}s 内 server.sessions 仍为空 — "
                    f"JS 未执行(植物人前端 bug 复现)。\n"
                    f"stderr 片段: {stderr_peek.decode('utf-8', errors='replace')}"
                )

            # 取第一个 session 记录
            first_sid = next(iter(daemon.sessions))
            first_rec = daemon.sessions[first_sid]
            seen_ts_before = first_rec.last_heartbeat

            # ── 断言2:≤15s 内 last_seen 前移(bug4 心跳回归钉) ───────────
            # Tauri 壳每 10s 发一次心跳(startHeartbeat in main.ts)。
            # 等待最多 15s 让心跳至少打一次。

            _WAIT_HEARTBEAT_S = 15.0
            deadline2 = time.monotonic() + _WAIT_HEARTBEAT_S
            heartbeat_advanced = False
            while time.monotonic() < deadline2:
                rec = daemon.sessions.get(first_sid)
                if rec is None:
                    # session 消失(reap?),取任意活跃的
                    sessions_now = daemon.sessions
                    if sessions_now:
                        rec = next(iter(sessions_now.values()))
                        seen_ts_before = rec.last_heartbeat
                    time.sleep(_POLL_INTERVAL_S)
                    continue
                if rec.last_heartbeat > seen_ts_before:
                    heartbeat_advanced = True
                    break
                time.sleep(_POLL_INTERVAL_S)

            if not heartbeat_advanced:
                pytest.fail(
                    f"断言2失败:{_WAIT_HEARTBEAT_S}s 内 last_seen 未前移 — "
                    f"心跳未到达 daemon(bug4 回归:壳发了心跳但 daemon 收不到?)。\n"
                    f"session_id={first_sid[:8]}… "
                    f"last_heartbeat_before={seen_ts_before:.3f}"
                )

        finally:
            # teardown:terminate 进程 + stop server,不留孤儿
            if proc is not None:
                try:
                    proc.terminate()
                    proc.wait(timeout=5.0)
                except Exception:
                    try:
                        proc.kill()
                    except Exception:
                        pass
            daemon.stop()


def test_committed_js_matches_ts_sources():
    """产物漂移钉(终审 minor):src/*.js 是入库的 tsc 产物(frontendDist 编译期嵌入),
    改了 .ts 忘记重建会让入库 JS 与源漂移 —— 重新 tsc 后 git diff 必须干净。
    """
    import shutil
    import subprocess
    from pathlib import Path

    shell_dir = Path(__file__).resolve().parents[2] / "desktop" / "shell"
    if shutil.which("npx") is None:
        import pytest
        pytest.skip("node 工具链不可用,无法验证产物一致性")
    r = subprocess.run(["npx", "tsc"], cwd=shell_dir, capture_output=True, text=True, timeout=120)
    assert r.returncode == 0, f"tsc 编译失败:{r.stderr[:300]}"
    d = subprocess.run(
        ["git", "diff", "--name-only", "--", "src/*.js"],
        cwd=shell_dir, capture_output=True, text=True, timeout=30,
    )
    assert d.stdout.strip() == "", (
        f"入库 JS 与 .ts 源漂移(改了 ts 没重建/没提交):\n{d.stdout}"
    )
