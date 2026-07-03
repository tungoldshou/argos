"""Internal documentation."""
from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, Literal, TypeVar, overload

from argos.i18n import t

T = TypeVar("T")
OnOSError = Literal["silent", "raise"]


# ── read_json_file ─────────────────────────────────────────
def read_json_file(
    path: Path, *, ErrorCls: type, on_os_error: OnOSError = "raise",
) -> dict | None:
    """Internal documentation."""
    import json as _json
    p = Path(path)
    try:
        text = p.read_text(encoding="utf-8")
    except FileNotFoundError:
        return None
    except UnicodeDecodeError as e:
        raise ErrorCls(t("core2.config_base.invalid_json", path=p, error=e)) from e
    except OSError as e:
        if on_os_error == "silent":
            return None
        raise ErrorCls(t("core2.config_base.read_failed", path=p, error=e)) from e
    try:
        data = _json.loads(text)
    except _json.JSONDecodeError as e:
        raise ErrorCls(t("core2.config_base.invalid_json", path=p, error=e)) from e
    if not isinstance(data, dict):
        raise ErrorCls(t("core2.config_base.not_object"))
    return data


# ── cached_singleton ──────────────────────────────────────
@overload
def cached_singleton(
    getter: Callable[[], T], *, _state: Any, ErrorCls: type,
) -> T: ...


def cached_singleton(getter: Callable[[], T], *, _state: Any, ErrorCls: type) -> T:
    """Internal documentation."""
    if _state is not None:
        return _state  # type: ignore[return-value]
    new = getter()
    return new


# ── reload_singleton ──────────────────────────────────────
def reload_singleton(getter: Callable[[], T], _state: Any, *, ErrorCls: type) -> T:
    """Internal documentation."""
    new = getter()
    return new
