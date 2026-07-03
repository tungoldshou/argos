from pathlib import Path
import os
import tomllib


def test_pytest_uses_isolated_argos_config_dir():
    cfg = Path(os.environ["ARGOS_CONFIG_DIR"])
    assert cfg != Path.home() / ".argos"
    assert "pytest-" in str(cfg)


def test_pytest_default_addopts_skip_slow_tests():
    pyproject = Path(__file__).resolve().parents[1] / "pyproject.toml"
    data = tomllib.loads(pyproject.read_text())
    addopts = data["tool"]["pytest"]["ini_options"]["addopts"]

    assert "-m" in addopts
    assert "not slow" in addopts


def test_pytest_slow_marker_documents_no_cov_command():
    pyproject = Path(__file__).resolve().parents[1] / "pyproject.toml"
    data = tomllib.loads(pyproject.read_text())
    markers = data["tool"]["pytest"]["ini_options"]["markers"]

    slow_marker = next(marker for marker in markers if marker.startswith("slow:"))
    assert "uv run pytest -m slow -q --no-cov" in slow_marker
