"""i18n keystone 自测 —— t() 的语言解析、回退、格式化、缺键不崩。

注意:tests/conftest.py 把 ARGOS_LANG 默认设为 zh。这里需要测 en 默认 / 切换时,
用 monkeypatch 显式覆盖 env。current_lang() 每次动态读 env,所以切换即时生效。
"""
from __future__ import annotations

import pytest

from argos import i18n


def test_default_lang_is_english(monkeypatch):
    """无 ARGOS_LANG → 默认 en(匹配 README/品牌/系统提示词)。"""
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
    """zh_CN / en-US / 大小写 / 未知 / 空 都归一到 en|zh。"""
    monkeypatch.setenv("ARGOS_LANG", raw)
    assert i18n.current_lang() == expect


def test_missing_key_returns_key_not_crash(monkeypatch):
    """缺键 → 诚实回退到 key 本身,绝不抛 KeyError。"""
    monkeypatch.setenv("ARGOS_LANG", "en")
    assert i18n.t("does.not.exist.anywhere") == "does.not.exist.anywhere"


def test_missing_in_zh_falls_back_to_en(monkeypatch):
    """zh 缺某 key 但 en 有 → 回退 en(绝不返回空 / key)。"""
    # 构造:往真实 en catalog 注入一个仅 en 有的 key(经缓存清理后生效)。
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
    """占位与 kwargs 不匹配 → 回退未格式化模板,绝不崩。"""
    monkeypatch.setenv("ARGOS_LANG", "en")
    i18n._catalog.cache_clear()
    from argos.locales import common as _common
    monkeypatch.setitem(_common.EN, "common._badfmt_probe", "need {missing}")
    i18n._catalog.cache_clear()
    try:
        assert i18n.t("common._badfmt_probe") == "need {missing}"  # 无 kwargs
    finally:
        i18n._catalog.cache_clear()


def test_en_zh_catalogs_have_same_keys():
    """每个目录模块的 EN/ZH 应覆盖同一组 key(防漏译 / 防孤儿键)。"""
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
