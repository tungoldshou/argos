"""13 条 hard shell rule + 系统路径 denylist + workspace 边界(spec §2.2 / §2.3)。

- HARD_SHELL_RULES:不可绕过的 shell 模式铁证(deny list 13 条)
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


# 13 条 hard shell rule(spec §2.2,exhaustive list)
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
    HardShellRule(
        # git 的 config 驱动执行原语:`-c core.sshCommand/fsmonitor/pager/editor/hooksPath=…`、
        # `-c alias.x=!cmd`、`-c key=!cmd`、`--exec-path`、`--upload-pack`、`--receive-pack` 都能
        # 让 git 跑任意命令(2026-06-20:Phase 2 删了旧 _validate_git,这里以 hard rule 兜底补回)。
        # 仅命中已知 RCE 向量,放过良性 `git -c user.name=…` 等。
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
    """对 run_command 命令字符串跑 13 条 hard rule。
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


# ── 非开发者 computer use HARD RULES(P6a §10 / CLAUDE.md §2)────────────────
# 适用于 computer_type_text 和 computer_open_app 动作的非开发者域强制确认规则。
# 规则可配但【默认集不可删】(hard 语义:无论 Trust Dial 档位,这些场景永远要求用户在场确认)。
# conductor 自治 run(trust≤L1)下直接拒并诚实说明"此类操作必须人在场确认"。

# 金融/验证码/密码关键词词表
# 识别 type_text 文本中可能涉及金融交易、身份验证等敏感输入模式。
# 锚在【文本内容模式】上:无法语义识别目标,因此用正则守卫明确场景。
_FINANCIAL_TEXT_PATTERN: Final[re.Pattern[str]] = re.compile(
    # 卡号:16位连续数字或4组4位(含空格/连字符分隔)
    r"\b(?:\d{4}[\s\-]?){3}\d{4}\b"
    # CVV/CVC:3-4位数字伴随 CVV/CVC/安全码关键词
    r"|(?:cvv|cvc|csc|安全码|安全代码)[\s:：]*\d{3,4}\b"
    # 验证码关键词 + 数字(6位数字伴随验证码语境)
    r"|(?:验证码|短信码|动态码|otp|one.?time.?password|verification.?code)[\s:：]*\d{4,8}\b"
    r"|\b\d{6}\b(?=.*(?:验证码|短信码|动态码|otp))"
    # 密码关键词(中英文):仅当关键词后跟分隔符(:或：或空格)再跟至少6个字符的实质值时触发。
    # 这样可避免命中 "password reset flow"、"密码 是必填项"、"口令 输入框" 等
    # 开发/文档上下文(这些场景中关键词后的内容不足6字符或是纯汉字描述)。
    # 分隔符组: [\s]*[:：][\s]* 或 \s{1,2}(?=\S{6}) 收紧为"有显式冒号"或"后跟6+非空白字符"。
    r"|(?:password|passwd|密码|口令|passcode)[\s]*[:：][\s]*\S{6,}"
    r"|(?:password|passwd|密码|口令|passcode)\s{1,3}(?=[A-Za-z0-9!@#$%^&*_\-]{6,})"
    # 银行卡/信用卡关键词
    r"|(?:card.?number|卡号|银行卡号|信用卡号)[\s:：]*[\d\s\-]+"
    # 转账金额关键词
    r"|(?:transfer.?amount|转账金额|汇款金额|付款金额)[\s:：]*[\d,，.]+",
    re.I,
)

# 支付/银行类 app 词表(open_app 动作强制 CONFIRM)
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
    """computer_type_text 文本命中金融/验证码模式 → 返回规则名;无命中 → None。

    用途:评估器(evaluator)在判断 computer_type_text 动作时调此函数。
    命中 → hard CONFIRM(Trust Dial L4 下仍必须问;conductor 自治直接拒)。

    规则基于文本内容模式,不做语义推断(诚实边界:无法识别目标 App 语义)。
    """
    if _FINANCIAL_TEXT_PATTERN.search(text):
        return "computer_type_financial_pattern"
    return None


def check_computer_open_app(app: str) -> str | None:
    """computer_open_app 的 app 名命中支付/银行 app 词表 → 返回规则名;无命中 → None。

    命中 → hard CONFIRM(不论 Trust Dial 档位,开启支付/银行类 app 永远要用户在场确认)。
    """
    if _PAYMENT_APP_PATTERN.search(app):
        return "computer_open_payment_app"
    return None


def check_computer_hard_rules(action: str, args: dict) -> str | None:
    """computer.* 动作的 HARD RULES 检查总入口。

    返回命中的规则名(str);无命中返 None。
    调用方(evaluator/broker)据返回值决定是否强制 CONFIRM 或在自治路径中直接拒。

    Args:
        action: broker action 字符串(如 "computer_type_text" / "computer_open_app")
        args:   动作参数 dict

    适用场景:
        · computer_type_text → 检查 text 字段的金融/验证码模式
        · computer_open_app  → 检查 app 字段的支付/银行词表
        · 其他 computer.* 动作 → 目前无词表规则,返 None(无命中)
    """
    if action == "computer_type_text":
        text = args.get("text", "") or ""
        return check_computer_type_text(str(text))
    if action == "computer_open_app":
        app = args.get("app", "") or ""
        return check_computer_open_app(str(app))
    return None
