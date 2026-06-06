"""12 条 hard shell rule + 系统路径 denylist + workspace 边界(spec §2.2 / §2.3)。

- HARD_SHELL_RULES:不可绕过的 shell 模式铁证(deny list 12 条)
- HARD_PATH_DENYLIST:系统路径前缀 tuple(写 /etc, ~/.ssh, ~/.aws 等拒)
- is_workspace_path:workspace 边界 host 侧 check(D14)
- is_env_file:workspace 内 .env 走"软 allow 可显式 trust"路径
- check_hard_shell(cmd):返命中的 rule name,无命中返 None
"""
from __future__ import annotations

import ipaddress
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Final
from urllib.parse import urlparse


@dataclass(frozen=True, slots=True)
class HardShellRule:
    name: str
    pattern: re.Pattern[str]
    reason: str
    applies_to: str = "run_command"
    action: str = "deny"


# 网络 allowlist(D1 锁:curl/wget 私域不拒)
_LOCAL_HOSTS: Final[frozenset[str]] = frozenset({"localhost", "127.0.0.1", "::1"})


def _is_private_host(url: str) -> bool:
    """URL host 属于 localhost / 私有 CIDR → True(allowlist 局部放宽)。"""
    try:
        host = urlparse(url).hostname or ""
    except Exception:
        return False
    if host in _LOCAL_HOSTS:
        return True
    try:
        return ipaddress.ip_address(host).is_private
    except ValueError:
        return False


# 12 条 hard shell rule(spec §2.2,exhaustive list)
HARD_SHELL_RULES: Final[tuple[HardShellRule, ...]] = (
    HardShellRule(
        name="rm_rf_root",
        pattern=re.compile(
            r"rm\s+(-[a-zA-Z]*[rRfF][a-zA-Z]*\s+)+/(?:\s|;|$|&|`|\|\|)"
            r"|rm\s+(?:-[a-zA-Z]+\s+)*--no-preserve-root\s+(?:-[a-zA-Z]+\s+)*/(?:\s|;|$|&|`|\|\|)"
        ),
        reason="Refusing rm -rf / (root wipe)",
    ),
    HardShellRule(
        name="rm_rf_home",
        pattern=re.compile(
            r"rm\s+(-[a-zA-Z]*[rRfF][a-zA-Z]*\s+)+(?:~|\$HOME|/Users/[^/\s]+)(?:\s|;|$|&|`|\|\|)"
        ),
        reason="Refusing rm -rf ~ or /Users/<name> (home wipe)",
    ),
    HardShellRule(
        name="dd_raw_disk",
        pattern=re.compile(
            r"\bdd\s+.*\bof=/dev/(?:sd|hd|nvme|disk)\w*\b"
        ),
        reason="Refusing dd write to /dev/(sd|hd|nvme|disk)",
    ),
    HardShellRule(
        name="mkfs_format",
        pattern=re.compile(r"\bmkfs(?:\.\w+)?\s+/dev/"),
        reason="Refusing mkfs on /dev/* (filesystem format)",
    ),
    HardShellRule(
        name="chmod_world_root",
        pattern=re.compile(r"chmod\s+(?:-R\s+)?777\s+/(?:\s|;|$|etc)"),
        reason="Refusing chmod 777 / or /etc",
    ),
    HardShellRule(
        name="chown_recursive_system",
        pattern=re.compile(
            r"chown\s+-R\s+\S+:\S+\s+/(?:etc|usr|var|System|bin|sbin)\b"
        ),
        reason="Refusing chown -R on system path",
    ),
    HardShellRule(
        name="fork_bomb",
        pattern=re.compile(r":\s*\(\s*\)\s*\{\s*:\s*\|\s*:\s*&\s*\}\s*;\s*:"),
        reason="Refusing fork bomb (:(){:|:&};:)",
    ),
    HardShellRule(
        name="sudo_dangerous",
        pattern=re.compile(r"\bsudo\s+(?:rm|dd|mkfs|chmod|chown)\b"),
        reason="Refusing sudo + dangerous command",
    ),
    HardShellRule(
        name="curl_pipe_sh",
        pattern=re.compile(
            r"\bcurl\b[^|]*?\|\s*(?:sudo\s+)?(?:sh|bash|zsh)\b"
        ),
        reason="Refusing curl | shell with non-allowlisted host",
    ),
    HardShellRule(
        name="wget_pipe_bash",
        pattern=re.compile(
            r"\bwget\b[^|]*?\|\s*(?:sudo\s+)?(?:sh|bash|zsh)\b"
        ),
        reason="Refusing wget | shell with non-allowlisted host",
    ),
    HardShellRule(
        name="eval_dynamic",
        pattern=re.compile(r"\beval\s+(?:\$\(|\$\{)"),
        reason="Refusing eval with dynamic input ($(...) or ${...})",
    ),
    HardShellRule(
        name="python_c_dangerous",
        pattern=re.compile(
            r"python[23]?\s+-c\s+[^\n|]*?(?:os\.system|subprocess|__import__|exec\(|eval\()"
        ),
        reason="Refusing python -c with os.system/subprocess/exec/eval",
    ),
)


def check_hard_shell(cmd: str) -> str | None:
    """对 run_command 命令字符串跑 12 条 hard rule。
    命中(非 allowlist 局部放宽)→ 返 rule name;无命中 → None。

    curl_pipe_sh / wget_pipe_bash 走 host 私有 CIDR allowlist(D1 锁)。"""
    for rule in HARD_SHELL_RULES:
        if rule.pattern.search(cmd):
            # 局部放宽:curl/wget 私域不算
            if rule.name in ("curl_pipe_sh", "wget_pipe_bash"):
                # 抽 URL 出来(从 cmd 里找 http(s)://host)
                url_match = re.search(r"https?://\S+", cmd)
                if url_match and _is_private_host(url_match.group(0)):
                    continue
            return rule.name
    return None


# ── 系统路径 denylist(spec §2.3) ───────────────────────────────────
def _home(p: str) -> str:
    return str(Path(p).expanduser())


HARD_PATH_DENYLIST: Final[tuple[str, ...]] = (
    "/etc/", "/usr/", "/bin/", "/sbin/", "/var/", "/System/", "/Library/",
    "/private/etc/", "/private/var/",
    _home("~/.ssh/"),
    _home("~/.aws/credentials"),
    _home("~/.gnupg/"),
    _home("~/.kube/config"),
)


def _resolve_str(path: str) -> str:
    """展开 ~ 并 resolve,失败返原串。"""
    if not path:
        return ""
    try:
        return str(Path(path).expanduser().resolve())
    except (OSError, RuntimeError):
        return str(Path(path).expanduser())


def is_system_path(path: str) -> bool:
    """绝对路径命中系统前缀 → True(D9 锁:deny list 而非 allow list)。"""
    p = _resolve_str(path)
    if not p.startswith("/"):
        return False
    return any(p.startswith(prefix) for prefix in HARD_PATH_DENYLIST)


def is_workspace_path(path: str, workspace: str | Path | None) -> bool:
    """workspace 边界 check(D14 锁:host 侧 Path.resolve() early check)。

    workspace 为 None / 空 / 路径不存在 → 返 False(走系统路径 check)。"""
    if not workspace:
        return False
    try:
        wp = Path(workspace).expanduser().resolve()
        pp = Path(path).expanduser().resolve()
    except (OSError, RuntimeError):
        return False
    try:
        pp.relative_to(wp)
        return True
    except ValueError:
        return False


def is_env_file(path: str) -> bool:
    """basename 匹配 .env / .env.<name> → True(spec §2.3 特殊路径)。"""
    name = Path(path).name
    if name == ".env":
        return True
    if name.startswith(".env."):
        return True
    return False


def is_env_template(path: str) -> bool:
    """.env.example / .env.sample / .env.template → True(教学用,允许)。"""
    name = Path(path).name
    return name in {".env.example", ".env.sample", ".env.template"}


def is_argos_own_env(path: str) -> bool:
    """~/.argos/.env → True(Argos 自己的 config,不 lock 自己)。"""
    name = Path(path).name
    if name != ".env":
        return False
    p = _resolve_str(path)
    argos_env = str(Path("~/.argos/.env").expanduser().resolve())
    return p == argos_env
