# -*- mode: python ; coding: utf-8 -*-
import sqlite_vec
from pathlib import Path
from PyInstaller.utils.hooks import collect_submodules, collect_data_files, copy_metadata

block_cipher = None

_vec_dir = Path(sqlite_vec.__file__).resolve().parent
_vec_binaries = [(str(p), "sqlite_vec") for p in _vec_dir.glob("*.dylib")]

hiddenimports = (
    collect_submodules("argos")
    + collect_submodules("smolagents")
    + collect_submodules("textual")
    + collect_submodules("rich")
    + ["sqlite_vec"]
)
_ROOT = Path(SPECPATH).parent
datas = (
    collect_data_files("textual", include_py_files=False)
    + collect_data_files("smolagents")
    + [(str(_ROOT / "argos" / "memory" / "schema.sql"), "argos/memory")]
    + [(str(p), "argos/skills_builtin")
       for p in (_ROOT / "argos" / "skills_builtin").glob("*.md")]
    + [(str(_ROOT / "packaging" / "VERSION"), "packaging")]
    + copy_metadata("argos-agent")
)

a = Analysis(
    ["../argos/__main__.py"],
    pathex=[".."],
    binaries=_vec_binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=["../argos/_pyinstaller_hooks"],
    excludes=["langchain", "langgraph", "fastapi", "uvicorn"],
    cipher=block_cipher,
)
pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)
exe = EXE(
    pyz, a.scripts, a.binaries, a.zipfiles, a.datas, [],
    name="argos",
    debug=False, bootloader_ignore_signals=False, strip=False, upx=False,
    console=True,
    target_arch="arm64",
    codesign_identity=None,
)
