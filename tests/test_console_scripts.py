"""console scripts 与文档一致性:文档命名的命令必须在 pyproject [project.scripts] 真实声明。

doc-drift:README/CLAUDE 把后台 daemon 进程命名为 `argosd`(auto-spawn),但 pyproject 过去
只声明 argos / argospkg → 用户敲 `argosd` 会 command not found。daemon/__main__.py 已有无参
main(),适合作 console script 入口。
"""
from __future__ import annotations

import tomllib
from pathlib import Path

_PYPROJECT = Path(__file__).resolve().parents[1] / "pyproject.toml"


def _scripts() -> dict:
    return tomllib.loads(_PYPROJECT.read_text(encoding="utf-8"))["project"]["scripts"]


def test_argosd_console_script_declared():
    """README:249 命名 `argosd` 后台进程 → pyproject 必须声明它指向真实无参入口。"""
    scripts = _scripts()
    assert scripts.get("argosd") == "argos.daemon.__main__:main"


def test_argosd_entry_target_is_callable():
    """入口 target 必须存在且无参可调(console script 调用不传参,从 argparse 读)。"""
    from argos.daemon.__main__ import main
    assert callable(main)


def test_all_console_script_targets_importable():
    """所有声明的 console script target 都必须可 import(防 drift:重命名后入口失效)。"""
    import importlib
    for name, target in _scripts().items():
        module_path, _, attr = target.partition(":")
        mod = importlib.import_module(module_path)
        assert hasattr(mod, attr), f"console script {name!r} target {target!r} 不存在"
