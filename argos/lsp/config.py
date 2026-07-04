from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Mapping

from argos import config
from argos import config_base
from argos.i18n import t
from argos.lsp.schema import SERVER_NAME_PATTERN


_SERVER_NAME_RE = re.compile(SERVER_NAME_PATTERN)


class LspConfigError(Exception):
    pass


@dataclass(frozen=True, slots=True)
class LspServerConfig:
    command: tuple[str, ...]
    filetypes: tuple[str, ...]
    disabled: bool = False
    init_options: Mapping[str, object] = field(default_factory=dict)
    env: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.command:
            raise ValueError(t("lsp.config.empty_command"))
        for ft in self.filetypes:
            if not ft.startswith("."):
                raise ValueError(t("lsp.config.filetype_no_dot", ft=ft))
        if not self.filetypes:
            raise ValueError(t("lsp.config.empty_filetypes"))


def _validate_server_name(name: str) -> None:
    if not _SERVER_NAME_RE.match(name):
        raise ValueError(t("lsp.config.invalid_server_name", name=name))


@dataclass(frozen=True, slots=True)
class LspConfig:
    version: int = 1
    servers: Mapping[str, LspServerConfig] = field(default_factory=dict)

    def __post_init__(self) -> None:
        for name in self.servers:
            _validate_server_name(name)

    @staticmethod
    def empty() -> "LspConfig":
        return LspConfig(version=1, servers={})

    def get_servers_for_filetype(self, ext: str) -> list[tuple[str, LspServerConfig]]:
        ext = ext if ext.startswith(".") else f".{ext}"
        result: list[tuple[str, LspServerConfig]] = []
        for name, sc in self.servers.items():
            if not sc.disabled and ext in sc.filetypes:
                result.append((name, sc))
        return result


BUILTIN_DEFAULT_CONFIG: LspConfig = LspConfig(
    version=1,
    servers={
        "python": LspServerConfig(
            command=("pyright-langserver", "--stdio"),
            filetypes=(".py", ".pyi"),
        ),
    },
)



LSP_CONFIG_PATH: Path | None = None


def _default_config_path() -> Path:
    return config.config_dir() / "lsp.json"


def _parse_server_config(name: str, raw: dict) -> LspServerConfig:
    if not isinstance(raw, dict):
        raise LspConfigError(t("lsp.config.server_not_object", name=name, type_name=type(raw).__name__))
    if "command" not in raw:
        raise LspConfigError(t("lsp.config.missing_command_field", name=name))
    if "filetypes" not in raw:
        raise LspConfigError(t("lsp.config.missing_filetypes_field", name=name))
    raw_cmd = raw["command"]
    if not isinstance(raw_cmd, list) or not raw_cmd:
        raise LspConfigError(t("lsp.config.command_not_array", name=name, value=raw_cmd))
    if not all(isinstance(c, str) and c for c in raw_cmd):
        raise LspConfigError(t("lsp.config.command_item_not_string", name=name))
    raw_ft = raw["filetypes"]
    if not isinstance(raw_ft, list) or not raw_ft:
        raise LspConfigError(t("lsp.config.filetypes_not_array", name=name))
    if not all(isinstance(ft, str) for ft in raw_ft):
        raise LspConfigError(t("lsp.config.filetypes_item_not_string", name=name))
    init_options = raw.get("init_options", {}) or {}
    if not isinstance(init_options, dict):
        raise LspConfigError(t("lsp.config.init_options_not_object", name=name))
    env = raw.get("env", {}) or {}
    if not isinstance(env, dict):
        raise LspConfigError(t("lsp.config.env_not_object", name=name))
    if not all(isinstance(k, str) and isinstance(v, str) for k, v in env.items()):
        raise LspConfigError(t("lsp.config.env_not_string_map", name=name))
    disabled = raw.get("disabled", False)
    if not isinstance(disabled, bool):
        raise LspConfigError(t("lsp.config.disabled_not_bool", name=name))
    try:
        return LspServerConfig(
            command=tuple(raw_cmd),
            filetypes=tuple(raw_ft),
            disabled=disabled,
            init_options=init_options,
            env=env,
        )
    except ValueError as e:
        raise LspConfigError(t("lsp.config.server_invalid", name=name, exc=e)) from e


def load(path: Path | None = None) -> LspConfig:
    p = path or LSP_CONFIG_PATH or _default_config_path()
    data = config_base.read_json_file(
        p, ErrorCls=LspConfigError, on_os_error="silent",
    )
    if data is None:
        return BUILTIN_DEFAULT_CONFIG
    if "version" not in data:
        raise LspConfigError(t("lsp.config.missing_version"))
    if data["version"] != 1:
        raise LspConfigError(t("lsp.config.version_mismatch", version=data["version"]))
    raw_servers = data.get("servers", {})
    if not isinstance(raw_servers, dict):
        raise LspConfigError(t("lsp.config.servers_not_object"))
    servers: dict[str, LspServerConfig] = {}
    for name, raw in raw_servers.items():
        try:
            _validate_server_name(name)
        except ValueError as e:
            raise LspConfigError(str(e)) from e
        servers[name] = _parse_server_config(name, raw)
    return LspConfig(version=1, servers=servers)


_config: LspConfig | None = None


def get_config() -> LspConfig:
    global _config
    if _config is None:
        _config = load()
    return _config


def reload_config(path: Path | None = None) -> LspConfig:
    global _config
    new = load(path)
    _config = new
    return _config


def _reset_config() -> None:
    global _config
    _config = None
