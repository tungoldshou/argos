"""slash 命令解析(spec §4.5)。纯解析,不渲染、不副作用——app.py 拿 SlashCommand 后分发。

MVP 子集:/yolo /undo /clear /retry /status /model /resume /cost
能力可见:/help /tools /skills /mcp
"""
from __future__ import annotations

from dataclasses import dataclass

# 命令 → 一句话说明(单一来源:/help 文案、slash 菜单、Tab 补全都从这里取,杜绝漂移)。
# 顺序 = slash 菜单展示顺序(按常用度排:能力发现在前,会话控制居中,待接线在后)。
COMMAND_HELP: dict[str, str] = {
    "help": "显示所有命令",
    "tools": "列出可调用的工具",
    "skills": "管理 skill 生态:list/install/remove/refresh/test (跑 argos skills ...)",
    "mcp": "列出 MCP 外部工具",
    "model": "查看 / 切换模型",
    "status": "当前运行状态",
    "cost": "本轮成本 + 缓存",
    "resume": "续上一次会话",
    "clear": "开新会话(清空)",
    "yolo": "放手执行(免审批；旧命令，同 /trust l4)",
    "trust": "查看 / 切换信任档位(/trust [l0|l1|l2|l3|l4|status])—替代 /yolo",
    "undo": "撤销本轮文件改动(还原到 run 起点)",
    "ledger": "查看当前 run 的行为账本(人话条目 + 撤销状态)",
    "retry": "重发上一条 user 消息",
    "plan": "进入 plan mode(审批后继续 act)—对齐 CC /plan",
    "hooks": "列出 / 重载 hooks 配置(/hooks, /hooks reload)",
    "lsp": "列出 / 重载 LSP 配置(/lsp, /lsp reload)",
    "permissions": "查看 / 重载权限配置(/permissions, /permissions reload)",
    "runs": "列出 / 后台 run(/runs, /runs {id} resume/cancel)—daemon 模式",
    "verify": "显式跑 verify_cmd(/verify [path])—用户复核 verify 门",
    "security-review": "安全审计(secrets + 依赖漏洞 + 危险 API)(/security-review [path])",
    "simplify": "代码重复 / 复杂度 / 死代码扫描(/simplify [path])",
    "eval": "Agent 自我评估 + A/B(/eval, /eval run <id>, /eval compare <a> <b>)",
    "routing": "查看 / 切换路由配置(/routing, /routing set <cat> <tier>)",
    "context": "查看当前 LLM 上下文分桶(/context, /context --json)",
}

COMMAND_NAMES: list[str] = list(COMMAND_HELP)

# Hidden commands(spec D16):parse_slash 仍识别为 known,但不显示在 /help / slash 菜单
# —memory 管理是 meta 操作,藏起来避免菜单过长
_HIDDEN_KNOWN: frozenset[str] = frozenset({"remember", "forget", "memory"})


def match_commands(text: str) -> list[tuple[str, str]]:
    """slash 菜单 / Tab 补全用:text 以 / 开头且尚未输入参数时,返回前缀匹配的 (name, desc) 列表
    (按 COMMAND_HELP 顺序)。非 slash / 已带参数(出现空格)/ 无匹配 → 空列表。"""
    s = text.lstrip()
    if not s.startswith("/"):
        return []
    body = s[1:]
    if " " in body:  # 已在输入参数,不再提示命令
        return []
    pref = body.lower()
    return [(n, d) for n, d in COMMAND_HELP.items() if n.startswith(pref)]


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
