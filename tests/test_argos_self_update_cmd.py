"""Internal documentation."""
import argparse
import json
import subprocess
from unittest.mock import patch


def test_self_update_cache_honors_argos_config_dir(tmp_path, monkeypatch, capsys):
    from argos import config as C
    from argos.__main__ import _cmd_self_update

    monkeypatch.setenv("ARGOS_CONFIG_DIR", str(tmp_path))
    monkeypatch.setattr(C, "_ENV", {})

    seen = {}

    def fake_check(**kwargs):
        seen["cache_path"] = kwargs["cache_path"]
        return None

    with patch("argos.core.updater.check_github_release", side_effect=fake_check):
        rc = _cmd_self_update(argparse.Namespace())
    capsys.readouterr()

    assert rc == 0
    assert seen["cache_path"] == tmp_path / ".last_update_check"


def test_startup_update_cache_honors_argos_config_dir(tmp_path, monkeypatch):
    from argos import config as C
    from argos.__main__ import _spawn_update_check

    monkeypatch.setenv("ARGOS_CONFIG_DIR", str(tmp_path))
    monkeypatch.setattr(C, "_ENV", {})

    seen = {}

    def fake_check(**kwargs):
        seen["cache_path"] = kwargs["cache_path"]
        return None

    with patch("argos.core.updater.check_github_release", side_effect=fake_check):
        _spawn_update_check()

    assert seen["cache_path"] == tmp_path / ".last_update_check"


def test_self_update_subcommand_registered():
    """Internal documentation."""
    result = subprocess.run(
        ["python", "-m", "argos", "self-update", "--help"],
        capture_output=True, text=True, timeout=10,
    )
    assert result.returncode == 0, f"self-update --help 失败: {result.stderr}"
    assert "self-update" in (result.stdout + result.stderr).lower()


def test_self_update_skips_cache(capsys):
    """Internal documentation."""
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
    """Internal documentation."""
    payload = json.dumps({"tag_name": "v0.1.0"}).encode()
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
