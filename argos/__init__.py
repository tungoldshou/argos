try:
    from importlib.metadata import version as _v
    __version__ = _v("argos-agent")
except Exception:  # noqa: BLE001
    import tomllib
    from pathlib import Path

    def _read_pyproject_version() -> str | None:
        p = Path(__file__).parent.parent / "pyproject.toml"
        if p.exists():
            data = tomllib.loads(p.read_text(encoding="utf-8"))
            return str(data["project"]["version"])
        return None

    __version__ = _read_pyproject_version() or "0.0.0+unknown"
