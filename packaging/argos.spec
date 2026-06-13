# -*- mode: python ; coding: utf-8 -*-
"""Argos PyInstaller spec —— arm64 单 binary(spec §10)。

捆:Textual + smolagents + sqlite-vec(.dylib) + mlx-embeddings(代码,权重懒下载不进 binary)。
不捆:MLX 模型权重(~300-600MB,首次用才下载到 ~/.cache,spec §5.4)。
路径相对【仓库根】(build_arm64.sh 在仓库根跑 `pyinstaller packaging/argos.spec`)。
"""
import sqlite_vec
from pathlib import Path
from PyInstaller.utils.hooks import collect_submodules, collect_data_files, copy_metadata

block_cipher = None

# sqlite-vec 的可加载扩展 .dylib(arm64 预编译),必须随包(CJK 向量召回主路径,spec §5.3)。
_vec_dir = Path(sqlite_vec.__file__).resolve().parent
_vec_binaries = [(str(p), "sqlite_vec") for p in _vec_dir.glob("*.dylib")]

hiddenimports = (
    collect_submodules("argos")
    + collect_submodules("smolagents")
    + collect_submodules("textual")
    + collect_submodules("rich")
    + ["sqlite_vec"]
)
# 包内运行时数据文件(PyInstaller 默认只收 .py,这些非 .py 数据必须显式带):
#   · memory/schema.sql —— ArgosStore 建库 schema(Path(__file__).with_name 定位)
#   · skills_builtin/*.md —— 内置技能正文
# SPECPATH = spec 所在目录(packaging/),.parent = 仓库根 → 用绝对源路径避免相对歧义。
_ROOT = Path(SPECPATH).parent
datas = (
    collect_data_files("textual", include_py_files=False)
    + collect_data_files("smolagents")
    + [(str(_ROOT / "argos" / "memory" / "schema.sql"), "argos/memory")]
    + [(str(p), "argos/skills_builtin")
       for p in (_ROOT / "argos" / "skills_builtin").glob("*.md")]
    # 版本号:同步 packaging/VERSION + dist-info 让 frozen bundle 报 0.1.0(非 0.0.0+unknown)
    + [(str(_ROOT / "packaging" / "VERSION"), "packaging")]
    + copy_metadata("argos-agent")
)

a = Analysis(
    # PyInstaller 按 spec 文件所在目录(packaging/)解析相对路径,故用 ../ 指回仓库根。
    ["../argos/__main__.py"],
    pathex=[".."],
    binaries=_vec_binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=["../argos/_pyinstaller_hooks"],
    excludes=["langchain", "langgraph", "fastapi", "uvicorn"],  # 旧栈不进新 binary(已非入口)
    cipher=block_cipher,
)
pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)
exe = EXE(
    pyz, a.scripts, a.binaries, a.zipfiles, a.datas, [],
    name="argos",
    debug=False, bootloader_ignore_signals=False, strip=False, upx=False,
    console=True,          # TUI 需要 console(终端)attach
    target_arch="arm64",   # Apple Silicon(踩过 x86_64 Rosetta 坑)
    codesign_identity=None,  # MVP 自签(notarize 放后面,spec §1)
)
