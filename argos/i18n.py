from __future__ import annotations

import importlib
import os
import pkgutil
from functools import lru_cache

_DEFAULT_LANG = "en"
_SUPPORTED = ("en", "zh")


def current_lang() -> str:
    raw = os.environ.get("ARGOS_LANG", _DEFAULT_LANG).strip().lower()
    main = raw.replace("-", "_").split("_", 1)[0]
    return main if main in _SUPPORTED else _DEFAULT_LANG


@lru_cache(maxsize=None)
def _catalog(lang: str) -> dict[str, str]:
    from argos import locales

    attr = "ZH" if lang == "zh" else "EN"
    names: list[str] = list(getattr(locales, "CATALOG_MODULES", []))
    try:
        for mod in pkgutil.iter_modules(locales.__path__):
            if not mod.name.startswith("_") and mod.name not in names:
                names.append(mod.name)
    except Exception:  # noqa: BLE001
        pass

    merged: dict[str, str] = {}
    for name in names:
        try:
            m = importlib.import_module(f"argos.locales.{name}")
        except Exception:  # noqa: BLE001
            continue
        d = getattr(m, attr, None)
        if isinstance(d, dict):
            merged.update(d)
    return merged


_ERROR_PREFIXES: tuple[str, ...] = ("错误:", "错误：", "Error:")


def is_error_result(s: object) -> bool:
    return isinstance(s, str) and s.startswith(_ERROR_PREFIXES)


def t(key: str, /, **kwargs: object) -> str:
    lang = current_lang()
    template = _catalog(lang).get(key)
    if template is None and lang != _DEFAULT_LANG:
        template = _catalog(_DEFAULT_LANG).get(key)
    if template is None:
        return key
    if not kwargs:
        return template
    try:
        return template.format(**kwargs)
    except (KeyError, IndexError, ValueError):
        return template


def available_keys(lang: str | None = None) -> frozenset[str]:
    return frozenset(_catalog(lang or current_lang()).keys())
