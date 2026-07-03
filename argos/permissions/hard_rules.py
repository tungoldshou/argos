"""Internal documentation."""
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


_LOCAL_HOSTS: Final[frozenset[str]] = frozenset({"localhost", "127.0.0.1", "::1"})


def _is_private_host(url: str) -> bool:
    """Internal documentation."""
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


HARD_SHELL_RULES: Final[tuple[HardShellRule, ...]] = (
    HardShellRule(
        name="rm_rf_root",
        pattern=re.compile(
            r"rm\s+(-[a-zA-Z]*[rRfF][a-zA-Z]*\s+)+(?:--\s+)?/+(?:\*|\.)?(?:\s|;|$|&|`|\|\|)"
            r"|rm\s+(?:-[a-zA-Z]+\s+)*--no-preserve-root\s+(?:-[a-zA-Z]+\s+)*(?:--\s+)?/+(?:\*|\.)?(?:\s|;|$|&|`|\|\|)"
        ),
        reason="Refusing rm -rf / (root wipe)",
    ),
    HardShellRule(
        name="rm_rf_home",
        pattern=re.compile(
            r"rm\s+(-[a-zA-Z]*[rRfF][a-zA-Z]*\s+)+(?:--\s+)?[\"']?(?:~|\$HOME|\$\{HOME\}|/Users/[^/\"'\s]+)[\"']?/*(?:\s|;|$|&|`|\|\|)"
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
    HardShellRule(
        name="git_config_exec",
        pattern=re.compile(
            r"(?i)\bgit\b[^\n]*?"
            r"(?:-c\s+(?:core\.(?:sshcommand|fsmonitor|pager|editor|hookspath)|protocol\.ext|alias\.|[\w.]+\s*=\s*!)"
            r"|--exec-path|--upload-pack|--receive-pack|\bext::)"
        ),
        reason="Refusing git config-driven exec (-c core.sshCommand/fsmonitor/pager/editor/hooksPath/alias, --exec-path/--upload-pack/--receive-pack)",
    ),
)


def check_hard_shell(cmd: str) -> str | None:
    """Internal documentation."""
    for rule in HARD_SHELL_RULES:
        if rule.pattern.search(cmd):
            if rule.name in ("curl_pipe_sh", "wget_pipe_bash"):
                url_match = re.search(r"https?://\S+", cmd)
                if url_match and _is_private_host(url_match.group(0)):
                    continue
            return rule.name
    return None


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
    """Internal documentation."""
    if not path:
        return ""
    try:
        return str(Path(path).expanduser().resolve())
    except (OSError, RuntimeError):
        return str(Path(path).expanduser())


def is_system_path(path: str) -> bool:
    """Internal documentation."""
    p = _resolve_str(path)
    if not p.startswith("/"):
        return False
    return any(p.startswith(prefix) for prefix in HARD_PATH_DENYLIST)


def is_workspace_path(path: str, workspace: str | Path | None) -> bool:
    """Internal documentation."""
    try:
        pp = Path(path).expanduser().resolve()
    except (OSError, RuntimeError):
        return False

    def _within(base) -> bool:
        try:
            pp.relative_to(Path(base).expanduser().resolve())
            return True
        except (ValueError, OSError, RuntimeError):
            return False

    if workspace and _within(workspace):
        return True
    from argos.config import extra_write_dirs
    return any(_within(extra) for extra in extra_write_dirs())


def is_env_file(path: str) -> bool:
    """Internal documentation."""
    name = Path(path).name
    if name == ".env":
        return True
    if name.startswith(".env."):
        return True
    return False


def is_env_template(path: str) -> bool:
    """Internal documentation."""
    name = Path(path).name
    return name in {".env.example", ".env.sample", ".env.template"}


def is_argos_own_env(path: str) -> bool:
    """Internal documentation."""
    name = Path(path).name
    if name != ".env":
        return False
    from argos import config
    p = _resolve_str(path)
    argos_dir = Path(config.get("ARGOS_CONFIG_DIR") or (Path.home() / ".argos")).expanduser()
    argos_env = str((argos_dir / ".env").resolve())
    return p == argos_env



_FINANCIAL_TEXT_PATTERN: Final[re.Pattern[str]] = re.compile(
    r"\b(?:\d{4}[\s\-]?){3}\d{4}\b"
    r"|(?:cvv|cvc|csc|安全码|安全代码)[\s:：]*\d{3,4}\b"
    r"|(?:验证码|短信码|动态码|otp|one.?time.?password|verification.?code)[\s:：]*\d{4,8}\b"
    r"|\b\d{6}\b(?=.*(?:验证码|短信码|动态码|otp))"
    r"|(?:password|passwd|密码|口令|passcode)[\s]*[:：][\s]*\S{6,}"
    r"|(?:password|passwd|密码|口令|passcode)\s{1,3}(?=[A-Za-z0-9!@#$%^&*_\-]{6,})"
    r"|(?:card.?number|卡号|银行卡号|信用卡号)[\s:：]*[\d\s\-]+"
    r"|(?:transfer.?amount|转账金额|汇款金额|付款金额)[\s:：]*[\d,，.]+",
    re.I,
)

_PAYMENT_APP_PATTERN: Final[re.Pattern[str]] = re.compile(
    r"\b(?:"
    r"支付宝|alipay"
    r"|微信支付|wechat.?pay"
    r"|paypal"
    r"|venmo"
    r"|zelle"
    r"|cashapp|cash.?app"
    r"|stripe"
    r"|square"
    r"|网银|online.?banking|internet.?banking"
    r"|招商银行|工商银行|建设银行|农业银行|中国银行|交通银行|浦发银行"
    r"|cmb|icbc|ccb|abc|boc|bocom"
    r"|chase|wells.?fargo|bank.?of.?america|citibank|capital.?one"
    r"|robinhood|coinbase|binance|okx|huobi|bitget"
    r"|证券|stock.?trading|etrade|schwab|fidelity"
    r")\b",
    re.I,
)


def check_computer_type_text(text: str) -> str | None:
    """Internal documentation."""
    if _FINANCIAL_TEXT_PATTERN.search(text):
        return "computer_type_financial_pattern"
    return None


def check_computer_open_app(app: str) -> str | None:
    """Internal documentation."""
    if _PAYMENT_APP_PATTERN.search(app):
        return "computer_open_payment_app"
    return None


def check_computer_hard_rules(action: str, args: dict) -> str | None:
    """Internal documentation."""
    if action == "computer_type_text":
        text = args.get("text", "") or ""
        return check_computer_type_text(str(text))
    if action == "computer_open_app":
        app = args.get("app", "") or ""
        return check_computer_open_app(str(app))
    return None
