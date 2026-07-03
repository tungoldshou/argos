try:
    from importlib.metadata import version as _v
    __version__ = _v("argos-agent")
except Exception:  # noqa: BLE001
    import sys
    from pathlib import Path

    def _read_version_file() -> str | None:
        """Try multiple locations for packaging/VERSION;return first hit's content."""
        candidates: list[Path] = []
        meipass = getattr(sys, "_MEIPASS", None)
        if meipass:
            candidates.append(Path(meipass) / "packaging" / "VERSION")
        exe = getattr(sys, "executable", None)
        if exe:
            candidates.append(Path(exe).parent / "packaging" / "VERSION")
        candidates.append(Path(__file__).parent.parent / "packaging" / "VERSION")
        for p in candidates:
            if p.exists():
                return p.read_text().strip()
        return None

    __version__ = _read_version_file() or "0.0.0+unknown"
