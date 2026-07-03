from __future__ import annotations

import tomllib
from pathlib import Path

_PYPROJECT = Path(__file__).resolve().parents[1] / "pyproject.toml"


def _scripts() -> dict:
    return tomllib.loads(_PYPROJECT.read_text(encoding="utf-8"))["project"]["scripts"]


def test_argosd_console_script_declared():
    scripts = _scripts()
    assert scripts.get("argosd") == "argos.daemon.__main__:main"


def test_argosd_entry_target_is_callable():
    from argos.daemon.__main__ import main
    assert callable(main)


def test_all_console_script_targets_importable():
    import importlib
    for name, target in _scripts().items():
        module_path, _, attr = target.partition(":")
        mod = importlib.import_module(module_path)
        assert hasattr(mod, attr), f"console script {name!r} target {target!r} 不存在"
