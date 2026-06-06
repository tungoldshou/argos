# 版本号优先走 importlib.metadata(从 pyproject/dist-info 读),fallback 读 packaging/VERSION。
try:
    from importlib.metadata import version as _v
    __version__ = _v("argos-agent")
except Exception:  # noqa: BLE001
    import sys
    from pathlib import Path

    def _read_version_file() -> str | None:
        """Try multiple locations for packaging/VERSION;return first hit's content."""
        candidates: list[Path] = []
        # 1. Frozen bundle(PyInstaller onefile/onedir):sys._MEIPASS 是解压根目录
        meipass = getattr(sys, "_MEIPASS", None)
        if meipass:
            candidates.append(Path(meipass) / "packaging" / "VERSION")
        # 2. Frozen bundle:binary 旁的 packaging/VERSION(spec 拷到 exe 目录的情形)
        exe = getattr(sys, "executable", None)
        if exe:
            candidates.append(Path(exe).parent / "packaging" / "VERSION")
        # 3. 开发模式:__init__.py 在 argos_agent/,parent.parent = 项目根
        candidates.append(Path(__file__).parent.parent / "packaging" / "VERSION")
        for p in candidates:
            if p.exists():
                return p.read_text().strip()
        return None

    __version__ = _read_version_file() or "0.0.0+unknown"
