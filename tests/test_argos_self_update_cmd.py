"""`argos self-update` 子命令:跳过缓存,主动查,有新版则打印升级指南。

注意:不下载,只告诉用户怎么升级(Cask / curl install.sh)。
"""
import argparse
import json
import subprocess
from unittest.mock import patch


def test_self_update_subcommand_registered():
    """`python -m argos self-update --help` 不应抛错(子命令已注册)。

    subprocess 测 argparse 接线(没有 mock 需求,直接走真 CLI)。
    """
    result = subprocess.run(
        ["python", "-m", "argos", "self-update", "--help"],
        capture_output=True, text=True, timeout=10,
    )
    assert result.returncode == 0, f"self-update --help 失败: {result.stderr}"
    assert "self-update" in (result.stdout + result.stderr).lower()


def test_self_update_skips_cache(capsys):
    """`self-update` 强制 force=True(跳过 7 天缓存),直接查 GitHub。

    mock 远端返新版,assert stdout 有 'available'。

    注意:不能走 subprocess — unittest.mock.patch 不跨进程传播。
    必须 in-process 直接调 _cmd_self_update,这样 patch 才生效。
    """
    payload = json.dumps({"tag_name": "v0.99.0"}).encode()
    from argos.__main__ import _cmd_self_update

    mock_resp = type("R", (), {
        "raise_for_status": lambda self: None,
        "json": lambda self: json.loads(payload),
        "content": payload,
    })()
    with patch("argos.core.updater.httpx.get", return_value=mock_resp) as mock_get:
        rc = _cmd_self_update(argparse.Namespace())
    out = capsys.readouterr().out + capsys.readouterr().err
    assert mock_get.called, "self-update 应走 httpx.get 直查 GitHub(force 跳过缓存)"
    assert rc == 0, f"self-update 返 {rc},应返 0"
    assert "0.99" in out or "available" in out.lower(), (
        f"未提示新版: {out!r}"
    )


def test_self_update_no_newer_version(capsys):
    """mock 远端返同版本,assert stdout 提示 'up to date' / 'latest'。"""
    payload = json.dumps({"tag_name": "v0.1.0"}).encode()  # 同 current
    from argos.__main__ import _cmd_self_update

    mock_resp = type("R", (), {
        "raise_for_status": lambda self: None,
        "json": lambda self: json.loads(payload),
        "content": payload,
    })()
    with patch("argos.core.updater.httpx.get", return_value=mock_resp):
        rc = _cmd_self_update(argparse.Namespace())
    out = (capsys.readouterr().out + capsys.readouterr().err).lower()
    assert rc == 0
    assert "latest" in out or "up to date" in out, f"未提示已是最新: {out!r}"
