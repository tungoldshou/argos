"""STT 配置:读 ~/.argos/config.json 的 stt 块。缺省让本地引擎零配置即用。

provider="local"(默认):本地 whisper,model=尺寸名(tiny/base/small/...)。
provider="cloud":云端,model=云模型 id,base_url+api_key_env;key 从 .env 解析。
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class SttConfig:
    provider: str = "local"          # "local" | "cloud"
    model: str = "base"              # local:whisper 尺寸;cloud:模型 id
    base_url: str | None = None
    api_key: str | None = None       # cloud 时从 .env 解析


def _config_dir(config_dir: Path | None) -> Path:
    if config_dir is not None:
        return config_dir
    import os
    return Path(os.environ.get("ARGOS_CONFIG_DIR") or (Path.home() / ".argos"))


def _read_env_value(cdir: Path, key_name: str) -> str | None:
    """从 ~/.argos/.env 读一个变量(简单 KEY=VALUE 解析)。"""
    envf = cdir / ".env"
    if not key_name or not envf.exists():
        return None
    for line in envf.read_text().splitlines():
        line = line.strip()
        if line.startswith(f"{key_name}="):
            return line[len(key_name) + 1:].strip()
    return None


def load_stt_config(config_dir: Path | None = None) -> SttConfig:
    """读 stt 块;无文件/无块 → 全默认(本地 base)。cloud 时解析 api_key。"""
    cdir = _config_dir(config_dir)
    cfile = cdir / "config.json"
    block: dict = {}
    if cfile.exists():
        try:
            block = (json.loads(cfile.read_text()) or {}).get("stt") or {}
        except json.JSONDecodeError:
            block = {}
    provider = block.get("provider", "local")
    model = block.get("model", "base")
    base_url = block.get("base_url")
    api_key = None
    if provider == "cloud":
        api_key = _read_env_value(cdir, block.get("api_key_env", ""))
    return SttConfig(provider=provider, model=model, base_url=base_url, api_key=api_key)
