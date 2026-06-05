# 版本号优先走 importlib.metadata(从 pyproject 读),fallback 读 packaging/VERSION。
try:
    from importlib.metadata import version as _v
    __version__ = _v("argos-agent")
except Exception:  # noqa: BLE001
    from pathlib import Path
    # __init__.py 在 argos_agent/ 下,parent.parent = 项目根
    _v_file = Path(__file__).parent.parent / "packaging" / "VERSION"
    __version__ = _v_file.read_text().strip() if _v_file.exists() else "0.0.0+unknown"
