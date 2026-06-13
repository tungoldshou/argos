"""LSP 系统(spec 2026-06-06):6 个真语言服务器原语(definition/references/hover/symbols/diagnostics)。

配置独立:`~/.argos/lsp.json`(同 hooks/mcp 模式);manager 模块级单例。
模块入口:
- `get_manager() -> LspManager` 拿当前 manager(惰性构造)
- `get_config() -> LspConfig` 拿当前配置(惰性加载)
- `reload_config() -> LspConfig` 重读盘
- `get_diagnostics(file: str) -> dict | None` 查 server 推的诊断
详细文档见 spec。"""
from __future__ import annotations

from argos.lsp.config import (
    BUILTIN_DEFAULT_CONFIG,
    LspConfig,
    LspConfigError,
    LspServerConfig,
)

__all__ = [
    "LspConfig",
    "LspServerConfig",
    "LspConfigError",
    "get_manager",
    "get_config",
    "reload_config",
    "get_diagnostics",
    "_reset_config",
]

# 模块级单例(同 hooks._config 模式,spec §2.1)
_config: LspConfig | None = None
_manager = None  # type: ignore[var-annotated]  # Task 4 实现 LspManager


def _reset_config() -> None:
    """清空单例(测试用)。"""
    global _config, _manager
    _config = None
    _manager = None


def get_config() -> LspConfig:
    """惰性加载 + 返回当前配置。模块级单例;`reload_config()` 改它。

    lsp.json 不存在 / 不可读 → 走 BUILTIN_DEFAULT_CONFIG(单 python server),不抛(spec §2.2)。
    """
    global _config
    if _config is None:
        from argos.lsp.config import load
        try:
            _config = load()
        except LspConfigError:
            # 真坏配(坏 JSON / 字段错)→ 走 built-in + 不抛(spec §3 "完全不启用")
            _config = BUILTIN_DEFAULT_CONFIG
    return _config


def reload_config() -> LspConfig:
    """重读 ~/.argos/lsp.json(用户显式 /lsp reload 走这里)。

    坏配置 → 保旧 + 抛 LspConfigError(spec §3 reload 行)。
    """
    from argos.lsp.config import load
    global _config
    new_cfg = load()
    _config = new_cfg
    return new_cfg


def get_manager():  # type: ignore[no-untyped-def]
    """惰性构造 + 返回当前 manager。配置变化 → 自动重建。"""
    global _manager
    if _manager is None:
        from argos.lsp.manager import LspManager
        _manager = LspManager(get_config())
    return _manager


def get_diagnostics(file: str):  # type: ignore[no-untyped-def]
    """查 server 推的诊断(供 `lsp_diagnostics` 工具和 TUI 渲染用)。"""
    if _manager is None:
        return None
    return _manager.get_diagnostics(file)  # type: ignore[union-attr]
