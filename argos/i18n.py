"""极简 i18n —— 把用户可见串路由到当前语言目录。

设计要点(finding #1/#14/#18/#23/#28:英文漏斗用户读不懂全中文界面 → 护城河隐形):
- 语言取自 `ARGOS_LANG`(默认 **en**,匹配 README / 品牌 / 已英文化的系统提示词);
  未知值或空 → 回退 en。允许 `zh_CN` / `en-US` 之类,取主语言段。
- 目录在 `argos/locales/*.py`,每个模块暴露 `EN` / `ZH` 两个 dict(key -> 模板串)。
  首次使用时**自动发现**并合并所有目录模块 —— 各 cluster 写各自的目录文件,并行不冲突。
- `t(key, **kw)`:查当前语言;缺 → 回退 en;再缺 → 回退 key 本身(**绝不抛 KeyError、绝不崩**,
  诚实降级)。模板用 `str.format(**kw)`;格式化失败 → 回退未格式化模板。

只路由**用户可见**串(CLI help / 向导 / splash / 诚实 widget / 状态栏 / 命令帮助 / 完成&错误行)。
内部日志、代码注释 / docstring、以及模型系统提示词(honesty.py,已全英文)**不走** i18n。
"""
from __future__ import annotations

import importlib
import os
import pkgutil
from functools import lru_cache

_DEFAULT_LANG = "en"
_SUPPORTED = ("en", "zh")


def current_lang() -> str:
    """当前语言码(en|zh)。每次动态读 env —— 便于测试切换 / 未来运行时切换。"""
    raw = os.environ.get("ARGOS_LANG", _DEFAULT_LANG).strip().lower()
    main = raw.replace("-", "_").split("_", 1)[0]
    return main if main in _SUPPORTED else _DEFAULT_LANG


@lru_cache(maxsize=None)
def _catalog(lang: str) -> dict[str, str]:
    """合并 argos/locales/*.py 中该语言的所有 dict(按 lang 缓存;模块静态,合一次即可)。

    冻结安全:PyInstaller 打包后 `pkgutil.iter_modules(__path__)` 常常发现不到子模块
    (模块在 frozen archive 里,不在文件系统),会导致打包版 t() 全部退化成 key、整个 UI 变英文键名。
    所以**先用 locales.CATALOG_MODULES 显式清单**(确定性、冻结安全),再用 pkgutil 兜底补任何
    未列出的目录(开发期便利)。两者去重合并。
    """
    from argos import locales

    attr = "ZH" if lang == "zh" else "EN"
    names: list[str] = list(getattr(locales, "CATALOG_MODULES", []))
    try:  # 兜底:开发期发现任何 CATALOG_MODULES 漏列的目录(冻结环境可能返回空,无害)
        for mod in pkgutil.iter_modules(locales.__path__):
            if not mod.name.startswith("_") and mod.name not in names:
                names.append(mod.name)
    except Exception:  # noqa: BLE001 —— pkgutil 在某些冻结环境会抛;有显式清单即可
        pass

    merged: dict[str, str] = {}
    for name in names:
        try:
            m = importlib.import_module(f"argos.locales.{name}")
        except Exception:  # noqa: BLE001 —— 单个坏/缺目录不该拖垮整个界面;诚实跳过
            continue
        d = getattr(m, attr, None)
        if isinstance(d, dict):
            merged.update(d)
    return merged


# 工具结果错误前缀(locale 无关哨兵):便宜地判定"某个工具结果串是不是错误",
# 不依赖具体语言文案 —— EN 错误串以 "Error:" 起、ZH 以 "错误:" 起,两者都认。
# 让 loop/dom_probe 等控制流判别器在切英文后仍正确识别工具错误(避免 en-only 漏判 bug)。
_ERROR_PREFIXES: tuple[str, ...] = ("错误:", "错误：", "Error:")


def is_error_result(s: object) -> bool:
    """该工具结果串是否为错误(任一已知语言的错误前缀开头)。控制流判别用,locale 无关。"""
    return isinstance(s, str) and s.startswith(_ERROR_PREFIXES)


def t(key: str, /, **kwargs: object) -> str:
    """查 key 的当前语言文案;缺键回退 en→key;`{name}` 占位用 kwargs 填充。"""
    lang = current_lang()
    template = _catalog(lang).get(key)
    if template is None and lang != _DEFAULT_LANG:
        template = _catalog(_DEFAULT_LANG).get(key)
    if template is None:
        return key  # 缺键 → 诚实回退到 key 本身,绝不崩
    if not kwargs:
        return template
    try:
        return template.format(**kwargs)
    except (KeyError, IndexError, ValueError):
        return template  # 占位不匹配 → 回退未格式化模板,绝不崩


def available_keys(lang: str | None = None) -> frozenset[str]:
    """该语言已登记的全部 key(测试 / 校验缺漏用)。"""
    return frozenset(_catalog(lang or current_lang()).keys())
