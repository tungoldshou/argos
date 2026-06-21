"""slash 命令解析(spec §4.5)。纯解析,不渲染、不副作用——app.py 拿 SlashCommand 后分发。

MVP 子集:/yolo /undo /clear /retry /status /model /resume /cost
能力可见:/help /tools /skills /mcp
"""
from __future__ import annotations

from dataclasses import dataclass

from argos.i18n import t

# 命令 → 一句话说明(单一来源:/help 文案、slash 菜单、Tab 补全都从这里取,杜绝漂移)。
# 顺序 = slash 菜单展示顺序(按常用度排:能力发现在前,会话控制居中,待接线在后)。
# i18n: 描述通过 t("cmd.<name>") 在运行时取当前语言版本。
_COMMAND_KEYS: list[str] = [
    "help", "setup", "tools", "skills", "mcp", "model", "status", "cost",
    "resume", "clear", "yolo", "trust", "undo", "ledger", "journal", "retry",
    "plan", "hooks", "lsp", "permissions", "runs", "orders", "confirm", "dismiss",
    "dream", "verify", "security-review", "simplify", "eval", "routing", "context",
]


def _build_command_help() -> dict[str, str]:
    """当前语言的命令描述字典(运行时惰性构建,语言切换时重新调用)。"""
    return {name: t(f"cmd.{name}") for name in _COMMAND_KEYS}


# COMMAND_HELP 保留为动态属性以兼容 `from argos.tui.commands import COMMAND_HELP`
# 用 module-level property 替代不易做到;改用函数调用点直接调 _build_command_help()。
# 为保向后兼容(现有测试 + app.py 直接 import COMMAND_HELP),保留一份快照作默认值——
# 测试在 ARGOS_LANG=zh 下跑,所以快照结果已是中文;app.py /help 分发路径已改为惰性重建。
COMMAND_HELP: dict[str, str] = _build_command_help()

COMMAND_NAMES: list[str] = list(COMMAND_HELP)

# Hidden commands(spec D16):parse_slash 仍识别为 known,但不显示在 /help / slash 菜单
# —memory 管理是 meta 操作,藏起来避免菜单过长
_HIDDEN_KNOWN: frozenset[str] = frozenset({"remember", "forget", "memory"})


def match_commands(text: str) -> list[tuple[str, str]]:
    """slash 菜单 / Tab 补全用:text 以 / 开头且尚未输入参数时,返回匹配的 (name, desc) 列表
    (按 COMMAND_HELP 顺序)。

    匹配策略(双层,优先级递降):
      1. 前缀匹配:name.startswith(pref)
      2. 子串回退:当前缀匹配无结果时,任意位置包含 pref 的命令(解决'security-review'
         输入'review'找不到的问题)

    非 slash / 已带参数(出现空格)/ 无匹配 → 空列表。
    """
    s = text.lstrip()
    if not s.startswith("/"):
        return []
    body = s[1:]
    if " " in body:  # 已在输入参数,不再提示命令
        return []
    pref = body.lower()
    prefix_matches = [(n, d) for n, d in COMMAND_HELP.items() if n.startswith(pref)]
    if prefix_matches or not pref:
        return prefix_matches
    # 子串回退:前缀无命中时尝试任意位置包含
    return [(n, d) for n, d in COMMAND_HELP.items() if pref in n]


@dataclass(frozen=True, slots=True)
class SlashCommand:
    name: str
    arg: str
    known: bool


def parse_slash(text: str) -> SlashCommand | None:
    """文本以 / 开头才视为命令;返回 (name, arg, known)。非命令返回 None。"""
    s = text.strip()
    if not s.startswith("/"):
        return None
    body = s[1:].strip()
    if not body:
        return None
    parts = body.split(None, 1)
    name = parts[0].lower()
    arg = parts[1].strip() if len(parts) > 1 else ""
    known = name in COMMAND_NAMES or name in _HIDDEN_KNOWN
    return SlashCommand(name=name, arg=arg, known=known)
