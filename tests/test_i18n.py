"""Internal documentation."""
from __future__ import annotations

import pytest

from argos import i18n


def test_default_lang_is_english(monkeypatch):
    """Internal documentation."""
    monkeypatch.delenv("ARGOS_LANG", raising=False)
    assert i18n.current_lang() == "en"
    assert i18n.t("common.enabled") == "enabled"


def test_zh_lang(monkeypatch):
    monkeypatch.setenv("ARGOS_LANG", "zh")
    assert i18n.current_lang() == "zh"
    assert i18n.t("common.enabled") == "已启用"


@pytest.mark.parametrize("raw,expect", [
    ("zh_CN", "zh"), ("en-US", "en"), ("ZH", "zh"), ("", "en"),
    ("fr", "en"), ("de_DE", "en"), ("  en  ", "en"),
])
def test_lang_normalization(monkeypatch, raw, expect):
    """Internal documentation."""
    monkeypatch.setenv("ARGOS_LANG", raw)
    assert i18n.current_lang() == expect


def test_missing_key_returns_key_not_crash(monkeypatch):
    """Internal documentation."""
    monkeypatch.setenv("ARGOS_LANG", "en")
    assert i18n.t("does.not.exist.anywhere") == "does.not.exist.anywhere"


def test_missing_in_zh_falls_back_to_en(monkeypatch):
    """Internal documentation."""
    monkeypatch.setenv("ARGOS_LANG", "zh")
    i18n._catalog.cache_clear()
    from argos.locales import common as _common
    monkeypatch.setitem(_common.EN, "common._enonly_probe", "EN-ONLY")
    i18n._catalog.cache_clear()
    try:
        assert i18n.t("common._enonly_probe") == "EN-ONLY"
    finally:
        i18n._catalog.cache_clear()


def test_kwargs_formatting(monkeypatch):
    monkeypatch.setenv("ARGOS_LANG", "en")
    i18n._catalog.cache_clear()
    from argos.locales import common as _common
    monkeypatch.setitem(_common.EN, "common._fmt_probe", "hello {name}, {n} left")
    i18n._catalog.cache_clear()
    try:
        assert i18n.t("common._fmt_probe", name="x", n=3) == "hello x, 3 left"
    finally:
        i18n._catalog.cache_clear()


def test_bad_format_falls_back_to_template(monkeypatch):
    """Internal documentation."""
    monkeypatch.setenv("ARGOS_LANG", "en")
    i18n._catalog.cache_clear()
    from argos.locales import common as _common
    monkeypatch.setitem(_common.EN, "common._badfmt_probe", "need {missing}")
    i18n._catalog.cache_clear()
    try:
        assert i18n.t("common._badfmt_probe") == "need {missing}"
    finally:
        i18n._catalog.cache_clear()


def test_daemon_no_key_hint_mentions_key_source(monkeypatch):
    monkeypatch.setenv("ARGOS_LANG", "en")
    msg = i18n.t("daemon.srv.no_key_run")
    assert "key source" in msg
    assert "existing environment variable" in msg
    assert "configure a model key" not in msg


def test_cli_no_key_hints_mention_key_source(monkeypatch):
    monkeypatch.setenv("ARGOS_LANG", "en")
    combined = "\n".join([
        i18n.t("cli.no_key_fallback", err="no key"),
        i18n.t("cli.exec.run_setup_hint"),
    ])
    assert "key source" in combined
    assert "existing environment variable" in combined


def test_tui_dream_no_key_fallback_uses_product_language(monkeypatch):
    monkeypatch.setenv("ARGOS_LANG", "en")
    msg = i18n.t("tui.dream.no_worker_key")
    assert "API key" in msg
    assert "argos setup" in msg
    assert "worker key" not in msg.lower()


def test_splash_hint_matches_ctrl_c_behavior(monkeypatch):
    monkeypatch.setenv("ARGOS_LANG", "en")
    msg = i18n.t("widget.splash_hint")
    assert "^C to quit" not in msg
    assert "^C" in msg
    assert "interrupt" in msg
    assert "^D" in msg


def test_eval_tb_help_matches_default_smoke_subset(monkeypatch):
    monkeypatch.setenv("ARGOS_LANG", "en")
    msg = i18n.t("eval.tb.cmd_help")
    assert "default: smoke" in msg.lower()
    assert "requires --subset" not in msg


def test_en_zh_catalogs_have_same_keys():
    """Internal documentation."""
    import importlib
    import pkgutil
    from argos import locales

    missing: list[str] = []
    for mod in pkgutil.iter_modules(locales.__path__):
        if mod.name.startswith("_"):
            continue
        m = importlib.import_module(f"argos.locales.{mod.name}")
        en = set(getattr(m, "EN", {}).keys())
        zh = set(getattr(m, "ZH", {}).keys())
        for k in en ^ zh:
            missing.append(f"{mod.name}: {k} (en={k in en} zh={k in zh})")
    assert not missing, "EN/ZH key 不对齐:\n" + "\n".join(missing)
