"""Internal documentation."""
from __future__ import annotations

import sys
from pathlib import Path
from unittest import mock

import pytest

from argos.sandbox import linux as linux_mod
from argos.sandbox.backend import SandboxBackend
from argos.sandbox.executor import SeatbeltExecutor
from argos.sandbox.linux import BwrapExecutor, UnshareExecutor, select_backend


def test_bwrap_executor_implements_sandbox_backend():
    """Internal documentation."""
    assert isinstance(BwrapExecutor(), SandboxBackend)
    assert isinstance(UnshareExecutor(), SandboxBackend)


def test_unshare_executor_implements_sandbox_backend():
    assert isinstance(UnshareExecutor(), SandboxBackend)


def test_select_backend_returns_seatbelt_on_macos():
    """Internal documentation."""
    with mock.patch.object(sys, "platform", "darwin"):
        cls = select_backend()
    assert cls is SeatbeltExecutor


def test_select_backend_returns_linux_on_linux_when_bwrap_available():
    """Internal documentation."""
    with mock.patch.object(sys, "platform", "linux"),\
         mock.patch.object(linux_mod, "_AVAILABLE_BACKEND", "bwrap", create=True):
        cls = select_backend()
    assert cls is BwrapExecutor


def test_select_backend_falls_back_to_unshare_when_bwrap_missing():
    """Internal documentation."""
    with mock.patch.object(sys, "platform", "linux"),\
         mock.patch.object(linux_mod, "_AVAILABLE_BACKEND", "unshare", create=True):
        cls = select_backend()
    assert cls is UnshareExecutor


def test_select_backend_raises_when_no_sandbox_available_on_linux():
    """Internal documentation."""
    with mock.patch.object(sys, "platform", "linux"),\
         mock.patch.object(linux_mod, "_AVAILABLE_BACKEND", None, create=True):
        with pytest.raises(RuntimeError, match="无可用 Linux 沙箱后端"):
            select_backend()


def test_bwrap_masks_active_argos_config_dir_secret_files(tmp_path, monkeypatch):
    """Internal documentation."""
    cfg = tmp_path / "cfg"
    cfg.mkdir()
    for name in (".env", "config.json", "mcp.json"):
        (cfg / name).write_text("secret")
    ws = tmp_path / "ws"
    ws.mkdir()
    monkeypatch.setenv("ARGOS_CONFIG_DIR", str(cfg))

    argv = linux_mod._bwrap_argv(ws, ["python3", "-c", "pass"])

    for name in (".env", "config.json", "mcp.json"):
        target = str(cfg / name)
        target_idx = argv.index(target)
        workspace_bind_idx = argv.index(str(ws))
        assert ["--ro-bind", "/dev/null", target] == argv[target_idx - 2: target_idx + 1]
        assert target_idx > workspace_bind_idx


def test_bwrap_masks_resolved_active_argos_config_dir_secret_files(tmp_path, monkeypatch):
    """Internal documentation."""
    real_cfg = tmp_path / "real-cfg"
    real_cfg.mkdir()
    for name in (".env", "config.json", "mcp.json"):
        (real_cfg / name).write_text("secret")
    link_cfg = tmp_path / "cfg-link"
    link_cfg.symlink_to(real_cfg, target_is_directory=True)
    ws = tmp_path / "ws"
    ws.mkdir()
    monkeypatch.setenv("ARGOS_CONFIG_DIR", str(link_cfg))

    argv = linux_mod._bwrap_argv(ws, ["python3", "-c", "pass"])

    for name in (".env", "config.json", "mcp.json"):
        for target_path in (link_cfg / name, real_cfg / name):
            target = str(target_path)
            target_idx = argv.index(target)
            assert ["--ro-bind", "/dev/null", target] == argv[target_idx - 2: target_idx + 1]


linux_only = pytest.mark.skipif(
    sys.platform != "linux", reason="Linux-only 真隔离测试(mac 跑平台/接口测试)",
)


@linux_only
def test_bwrap_blocks_network(tmp_path):
    """Internal documentation."""
    cls = select_backend()
    if cls is not BwrapExecutor:
        pytest.skip(f"bwrap 不可用,跳过(用 {cls.__name__})")
    ex = cls()
    ex.spawn(workspace=tmp_path, namespace={"__authorized_imports__": ["subprocess"]},
             allow_workflow=True, read_only=False)
    try:
        res = ex.exec_code(
            "import subprocess\n"
            "r = subprocess.run(['curl', '-sSf', '-m', '2', 'https://example.com/'],\n"
            "                   capture_output=True, text=True, timeout=5)\n"
            "print('returncode=' + str(r.returncode))"
        )
        assert "returncode=" in res.stdout
        assert "returncode=0" not in res.stdout, f"网络竟能外泄:{res.stdout!r}"
    finally:
        ex.close()


@linux_only
def test_bwrap_blocks_write_outside_workspace(tmp_path):
    """Internal documentation."""
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
        assert "WRITE_BLOCKED" in res.stdout or "WRITE_OK" not in res.stdout, (
            f"workspace 外写竟能成功:{res.stdout!r}"
        )
    finally:
        ex.close()


@linux_only
def test_bwrap_allows_write_inside_workspace(tmp_path):
    """Internal documentation."""
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


@linux_only
def test_bwrap_masks_credential_dirs(tmp_path, monkeypatch):
    """Internal documentation."""
    cls = select_backend()
    if cls is not BwrapExecutor:
        pytest.skip(f"非 bwrap 后端,跳过(用 {cls.__name__})")
    fake_home = tmp_path / "home"
    (fake_home / ".ssh").mkdir(parents=True)
    secret = "SUPER_SECRET_PRIVATE_KEY_DO_NOT_LEAK"
    (fake_home / ".ssh" / "id_rsa").write_text(secret)
    monkeypatch.setenv("HOME", str(fake_home))
    ws = tmp_path / "ws"
    ws.mkdir()
    ex = cls()
    ex.spawn(workspace=ws, namespace={"__authorized_imports__": ["pathlib"]},
             allow_workflow=True, read_only=False)
    try:
        res = ex.exec_code(
            "import pathlib\n"
            "p = pathlib.Path.home() / '.ssh' / 'id_rsa'\n"
            "try:\n"
            "    print('CONTENT=' + p.read_text())\n"
            "except Exception as e:\n"
            "    print('READ_BLOCKED=' + type(e).__name__)"
        )
        blob = (res.stdout or "") + (res.value_repr or "") + (res.exc or "")
        assert secret not in blob, f"凭据竟可读(遮蔽失效):{blob!r}"
    finally:
        ex.close()
