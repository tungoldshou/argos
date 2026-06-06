"""LSP 配置 dataclass + 加载/校验/缓存(spec §2.2 / §3 / D11)。

- `LspServerConfig` / `LspConfig` 全部 frozen dataclass(immutability)。
- `command` 走 tuple 替代 list(避免 list 不可哈希 + frozen 友好)。
- `load()` 手写最小校验(避免引入 jsonschema 依赖);坏配置 → `LspConfigError`。
- 模块级 `_config` 单例;`get_config()` 惰性加载,`reload_config()` 重新读盘。
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Mapping

from argos_agent.lsp.schema import SERVER_NAME_PATTERN


_SERVER_NAME_RE = re.compile(SERVER_NAME_PATTERN)


class LspConfigError(Exception):
    """LSP 配置加载 / 校验失败。坏配置 → 报错,绝不部分加载(spec D11)。"""


@dataclass(frozen=True, slots=True)
class LspServerConfig:
    """单条 LSP server 配置(spec §2.2)。"""
    command: tuple[str, ...]   # argv 数组(避开注入)
    filetypes: tuple[str, ...]  # 以 . 开头的 ext((".py", ".pyi"))
    disabled: bool = False
    init_options: Mapping[str, object] = field(default_factory=dict)
    env: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.command:
            raise ValueError("LspServerConfig.command 不能为空(否则 spawn 空 argv)")
        for ft in self.filetypes:
            if not ft.startswith("."):
                raise ValueError(
                    f"LspServerConfig.filetypes 项必须以 . 开头(如 '.py'),收到 {ft!r}"
                )
        if not self.filetypes:
            raise ValueError("LspServerConfig.filetypes 不能为空(0 server 服务 = 死代码)")


def _validate_server_name(name: str) -> None:
    if not _SERVER_NAME_RE.match(name):
        raise ValueError(
            f"server name {name!r} 非法:仅允许 ASCII 字母数字 + _ + -(spec §2.2)"
        )


@dataclass(frozen=True, slots=True)
class LspConfig:
    """完整 LSP 配置:version + servers dict(name → LspServerConfig)。"""
    version: int = 1
    servers: Mapping[str, LspServerConfig] = field(default_factory=dict)

    def __post_init__(self) -> None:
        for name in self.servers:
            _validate_server_name(name)

    @staticmethod
    def empty() -> "LspConfig":
        """全等 manager 禁用的空配置(0 server)。"""
        return LspConfig(version=1, servers={})

    def get_servers_for_filetype(self, ext: str) -> list[tuple[str, LspServerConfig]]:
        """返所有 filetypes 包含 ext 的 server(给 sync_file 派发用)。"""
        ext = ext if ext.startswith(".") else f".{ext}"
        result: list[tuple[str, LspServerConfig]] = []
        for name, sc in self.servers.items():
            if not sc.disabled and ext in sc.filetypes:
                result.append((name, sc))
        return result


# built-in 默认(spec §2.2):仅 python,不偷偷启动用户没装的 server
BUILTIN_DEFAULT_CONFIG: LspConfig = LspConfig(
    version=1,
    servers={
        "python": LspServerConfig(
            command=("pyright-langserver", "--stdio"),
            filetypes=(".py", ".pyi"),
        ),
    },
)


# ── 加载 / 校验(spec §2.2 / §3 / D11)────────────────────────────────────

LSP_CONFIG_PATH: Path = Path.home() / ".argos" / "lsp.json"


def _parse_server_config(name: str, raw: dict) -> LspServerConfig:
    if not isinstance(raw, dict):
        raise LspConfigError(f"server {name!r} 必须是 object,收到 {type(raw).__name__}")
    if "command" not in raw:
        raise LspConfigError(f"server {name!r} 缺 'command' 字段")
    if "filetypes" not in raw:
        raise LspConfigError(f"server {name!r} 缺 'filetypes' 字段")
    raw_cmd = raw["command"]
    if not isinstance(raw_cmd, list) or not raw_cmd:
        raise LspConfigError(
            f"server {name!r} 'command' 必须是非空 array(argv 数组,不是 shell 字符串),收到 {raw_cmd!r}"
        )
    if not all(isinstance(c, str) and c for c in raw_cmd):
        raise LspConfigError(f"server {name!r} 'command' 项必须是非空 string")
    raw_ft = raw["filetypes"]
    if not isinstance(raw_ft, list) or not raw_ft:
        raise LspConfigError(f"server {name!r} 'filetypes' 必须是非空 array")
    if not all(isinstance(ft, str) for ft in raw_ft):
        raise LspConfigError(f"server {name!r} 'filetypes' 项必须是 string")
    init_options = raw.get("init_options", {}) or {}
    if not isinstance(init_options, dict):
        raise LspConfigError(f"server {name!r} 'init_options' 必须是 object")
    env = raw.get("env", {}) or {}
    if not isinstance(env, dict):
        raise LspConfigError(f"server {name!r} 'env' 必须是 object")
    if not all(isinstance(k, str) and isinstance(v, str) for k, v in env.items()):
        raise LspConfigError(f"server {name!r} 'env' 项必须是 string→string 映射")
    disabled = raw.get("disabled", False)
    if not isinstance(disabled, bool):
        raise LspConfigError(f"server {name!r} 'disabled' 必须是 bool")
    try:
        return LspServerConfig(
            command=tuple(raw_cmd),
            filetypes=tuple(raw_ft),
            disabled=disabled,
            init_options=init_options,
            env=env,
        )
    except ValueError as e:
        raise LspConfigError(f"server {name!r} 非法: {e}") from e


def load(path: Path | None = None) -> LspConfig:
    """加载 + 校验 ~/.argos/lsp.json。文件不存在 / 不可读 → 返 BUILTIN_DEFAULT_CONFIG。

    Args:
        path: 显式路径(测试用);None 时读 LSP_CONFIG_PATH。

    Returns:
        LspConfig 实例。

    Raises:
        LspConfigError: JSON 坏字 / 字段类型错 / version 不匹配 / server name 非法。
    """
    p = path or LSP_CONFIG_PATH
    try:
        text = p.read_text(encoding="utf-8")
    except (FileNotFoundError, OSError):
        # 不存在 / 不可读 → 走 built-in 默认(spec §2.2 / §3)
        return BUILTIN_DEFAULT_CONFIG
    try:
        data = json.loads(text)
    except json.JSONDecodeError as e:
        raise LspConfigError(f"{p} 不是合法 JSON: {e}") from e
    if not isinstance(data, dict):
        raise LspConfigError("lsp.json 顶层必须是 object")
    if "version" not in data:
        raise LspConfigError("lsp.json 缺 'version' 字段")
    if data["version"] != 1:
        raise LspConfigError(
            f"lsp.json version={data['version']} 不匹配(host 仅支持 v1)"
        )
    raw_servers = data.get("servers", {})
    if not isinstance(raw_servers, dict):
        raise LspConfigError("'servers' 必须是 object(server name → config)")
    servers: dict[str, LspServerConfig] = {}
    for name, raw in raw_servers.items():
        try:
            _validate_server_name(name)
        except ValueError as e:
            raise LspConfigError(str(e)) from e
        servers[name] = _parse_server_config(name, raw)
    return LspConfig(version=1, servers=servers)
