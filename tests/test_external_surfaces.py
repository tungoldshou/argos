from __future__ import annotations

from pathlib import Path

from argos.external_surfaces import external_surface_warnings


def test_no_config_no_warnings(tmp_path: Path):
    assert external_surface_warnings(tmp_path) == []


def test_hooks_config_warns(tmp_path: Path):
    (tmp_path / "hooks.json").write_text("{}", encoding="utf-8")
    w = external_surface_warnings(tmp_path)
    assert len(w) == 1 and "hooks" in w[0]


def test_lsp_config_warns(tmp_path: Path):
    (tmp_path / "lsp.json").write_text("{}", encoding="utf-8")
    w = external_surface_warnings(tmp_path)
    assert len(w) == 1 and "lsp" in w[0]


def test_mcp_config_warns(tmp_path: Path):
    (tmp_path / "mcp.json").write_text("{}", encoding="utf-8")
    w = external_surface_warnings(tmp_path)
    assert len(w) == 1 and "mcp" in w[0]


def test_all_three_warn(tmp_path: Path):
    for name in ("hooks.json", "lsp.json", "mcp.json"):
        (tmp_path / name).write_text("{}", encoding="utf-8")
    w = external_surface_warnings(tmp_path)
    assert len(w) == 3
    joined = " ".join(w)
    assert "lsp" in joined and "mcp" in joined and "hooks" in joined


def test_default_path_honors_argos_config_dir(tmp_path: Path, monkeypatch):
    cfg_dir = tmp_path / ".argos"
    cfg_dir.mkdir()
    (cfg_dir / "mcp.json").write_text("{}", encoding="utf-8")
    monkeypatch.setenv("ARGOS_CONFIG_DIR", str(cfg_dir))

    w = external_surface_warnings()

    assert len(w) == 1 and "mcp" in w[0]


def test_warning_mentions_configured_path(tmp_path: Path):
    cfg_dir = tmp_path / "custom-config"
    cfg_dir.mkdir()
    (cfg_dir / "hooks.json").write_text("{}", encoding="utf-8")
    (cfg_dir / "lsp.json").write_text("{}", encoding="utf-8")
    (cfg_dir / "mcp.json").write_text("{}", encoding="utf-8")

    warnings = external_surface_warnings(cfg_dir)
    joined = "\n".join(warnings)

    assert str(cfg_dir / "hooks.json") in joined
    assert str(cfg_dir / "lsp.json") in joined
    assert str(cfg_dir / "mcp.json") in joined
    assert "~/.argos" not in joined
