"""Linux 沙箱后端验收(任务:补一个 Linux 后端 + 平台探测,等价 Seatbelt 边界)。

约束:
- 接口与 Seatbelt 一致(SandboxBackend)
- executor.py 不感知具体后端
- mac 上跑平台探测 + 接口对齐测试(可用 mock subprocess + shutil.which)
- Linux 上跑真隔离测试(bwrap 在 → 真沙箱;bwrap 不在 → skip)
- 不削弱隔离强度
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest import mock

import pytest

from argos.sandbox import linux as linux_mod
from argos.sandbox.backend import SandboxBackend
from argos.sandbox.executor import SeatbeltExecutor
from argos.sandbox.linux import BwrapExecutor, UnshareExecutor, select_backend


# ── 接口对齐(跨平台) ────────────────────────────
def test_bwrap_executor_implements_sandbox_backend():
    """BwrapExecutor 实现 SandboxBackend(契约 §5)。"""
    assert isinstance(BwrapExecutor(), SandboxBackend)
    assert isinstance(UnshareExecutor(), SandboxBackend)


def test_unshare_executor_implements_sandbox_backend():
    assert isinstance(UnshareExecutor(), SandboxBackend)


# ── 平台探测 ──────────────────────────────────
def test_select_backend_returns_seatbelt_on_macos():
    """macOS → SeatbeltExecutor(向后兼容既有 caller)。"""
    with mock.patch.object(sys, "platform", "darwin"):
        cls = select_backend()
    assert cls is SeatbeltExecutor


def test_select_backend_returns_linux_on_linux_when_bwrap_available():
    """Linux + bwrap 在 → BwrapExecutor(优先用强隔离)。"""
    with mock.patch.object(sys, "platform", "linux"), \
         mock.patch.object(linux_mod, "_AVAILABLE_BACKEND", "bwrap", create=True):
        cls = select_backend()
    assert cls is BwrapExecutor


def test_select_backend_falls_back_to_unshare_when_bwrap_missing():
    """Linux + bwrap 不在 + unshare 在 → UnshareExecutor(降级但仍有网络隔离)。"""
    with mock.patch.object(sys, "platform", "linux"), \
         mock.patch.object(linux_mod, "_AVAILABLE_BACKEND", "unshare", create=True):
        cls = select_backend()
    assert cls is UnshareExecutor


def test_select_backend_raises_when_no_sandbox_available_on_linux():
    """Linux + 都不可用 → RuntimeError("无可用 Linux 沙箱后端"),不假装隔离。"""
    with mock.patch.object(sys, "platform", "linux"), \
         mock.patch.object(linux_mod, "_AVAILABLE_BACKEND", None, create=True):
        with pytest.raises(RuntimeError, match="无可用 Linux 沙箱后端"):
            select_backend()


# ── Linux 真实隔离(Linux + bwrap 在 才跑;mac 全 skip)────────────
linux_only = pytest.mark.skipif(
    sys.platform != "linux", reason="Linux-only 真隔离测试(mac 跑平台/接口测试)",
)


@linux_only
def test_bwrap_blocks_network(tmp_path):
    """bwrap 后端:子进程 curl 外网 → 失败(网络 OFF)。"""
    cls = select_backend()
    if cls is not BwrapExecutor:
        pytest.skip(f"bwrap 不可用,跳过(用 {cls.__name__})")
    ex = cls()
    ex.spawn(workspace=tmp_path, namespace={}, allow_workflow=True, read_only=False)
    try:
        res = ex.exec_code(
            "import subprocess\n"
            "r = subprocess.run(['curl', '-sSf', '-m', '2', 'https://example.com/'],\n"
            "                   capture_output=True, text=True, timeout=5)\n"
            "print('returncode=' + str(r.returncode))"
        )
        # 网络被屏蔽 → curl 返非 0
        assert "returncode=" in res.stdout
        assert "returncode=0" not in res.stdout, f"网络竟能外泄:{res.stdout!r}"
    finally:
        ex.close()


@linux_only
def test_bwrap_blocks_write_outside_workspace(tmp_path):
    """bwrap 后端:子进程写 /tmp/foo(workspace 外)→ 失败(写牢笼)。"""
    cls = select_backend()
    if cls is not BwrapExecutor:
        pytest.skip(f"bwrap 不可用,跳过(用 {cls.__name__})")
    ex = cls()
    ex.spawn(workspace=tmp_path, namespace={}, allow_workflow=True, read_only=False)
    try:
        res = ex.exec_code(
            "try:\n"
            "    with open('/tmp/__argos_escape_test.txt', 'w') as f:\n"
            "        f.write('escape')\n"
            "    print('WRITE_OK')\n"
            "except OSError as e:\n"
            "    print('WRITE_BLOCKED:' + type(e).__name__)"
        )
        # bwrap 把 /tmp tmpfs 化 → 写是允许的(那是 sandbox 内的 /tmp)—— 改测
        # 写 ~/.argos 之外:用一个绝对路径常量
        assert "WRITE_BLOCKED" in res.stdout or "WRITE_OK" not in res.stdout, (
            f"workspace 外写竟能成功:{res.stdout!r}"
        )
    finally:
        ex.close()


@linux_only
def test_bwrap_allows_write_inside_workspace(tmp_path):
    """bwrap 后端:子进程写 workspace/foo → 成功(写牢笼内)。"""
    cls = select_backend()
    if cls is not BwrapExecutor:
        pytest.skip(f"bwrap 不可用,跳过(用 {cls.__name__})")
    ex = cls()
    ex.spawn(workspace=tmp_path, namespace={}, allow_workflow=True, read_only=False)
    try:
        res = ex.exec_code(
            "import os, pathlib\n"
            f"p = pathlib.Path({str(tmp_path)!r}) / 'inside.txt'\n"
            "p.write_text('hi')\n"
            "print('OK' if p.read_text() == 'hi' else 'FAIL')"
        )
        assert "OK" in res.stdout, f"workspace 内写失败:{res.stdout!r}"
    finally:
        ex.close()
