"""配置加载公共助手(任务:5 个 config 抽样板 —— lsp/hooks/permissions/routing)。

设计要点:
- 不合并各模块 schema(领域专属校验留在各模块);只抽"读 JSON 文件 + 解析 + 单例缓存"
  这条最一致的真样板。
- `read_json_file` 严格保持现有行为(错误消息格式、文件不在返 None)。
  OSError 行为按"caller 偏好"配置:on_os_error="silent" 返 None(lsp 旧行为),
  on_os_error="raise" 包成 ErrorCls 抛(hooks/permissions 旧行为)。
- `cached_singleton` / `reload_singleton` 与各模块的 `_config` 模式等价(惰性 + 保旧 + 不缓存错误)。
- 根 `config.py` 不用本助手(fail-closed + 每次重读,语义不同)。
"""
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
    """读 path + 解析 JSON + 顶层必须 object。

    行为契约(与各模块 load() 旧行为一致):
    - FileNotFoundError → 返 None(让 caller 决定"无配置返什么":empty()/BUILTIN/raise)
    - OSError:
        on_os_error="silent" → 返 None(lsp 旧行为:连 PermissionError 也吞,回 BUILTIN)
        on_os_error="raise"  → raise ErrorCls(f"读 {path} 失败: {inner}")(hooks/permissions 旧行为)
    - json.JSONDecodeError → raise ErrorCls(f"{path} 不是合法 JSON: {inner}")
    - 顶层非 dict → raise ErrorCls("顶层必须是 object")
    """
    import json as _json
    p = Path(path)
    try:
        text = p.read_text(encoding="utf-8")
    except FileNotFoundError:
        return None
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
    """单例缓存。模块级用法:

        _config: HooksConfig | None = None
        def get_config() -> HooksConfig:
            global _config
            _config = cached_singleton(load, _state=_config, ErrorCls=HooksConfigError)
            return _config

    行为契约(与各模块 _config 模式等价):
    - _state is None(首次 / 之前失败)→ 调 getter(),把结果存进 _state 后返回
    - _state 不为 None → 直接返 _state(不再调 getter)
    - getter 抛 ErrorCls → 不写 _state(让下次再试),让异常透传(spec D11 不静默)
    """
    if _state is not None:
        return _state  # type: ignore[return-value]
    new = getter()
    return new  # 调用方负责把 new 赋给 _state


# ── reload_singleton ──────────────────────────────────────
def reload_singleton(getter: Callable[[], T], _state: Any, *, ErrorCls: type) -> T:
    """reload:新配置覆盖旧;失败 → 保旧 + 抛(spec §3 / D11)。

    行为契约:
    - 调 getter() 拿新配置
    - 成功 → 用新值替换 _state(调用方负责把结果赋回 _state 字段)
    - 失败(ErrorCls 异常)→ _state 不变,异常透传
    """
    new = getter()
    return new
