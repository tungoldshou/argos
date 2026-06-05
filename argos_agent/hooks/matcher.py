"""Hook matcher 逻辑(spec §2.2 / §4.2)。

- Pre/Post 事件:matcher 正则(可选)匹 `tool_names`;空 / `*` / None = 全匹配。
- 其他事件(Stop / UserPromptSubmit / SessionStart):忽略 matcher,所有 entry 的 hooks 返。
- 同事件多 entry 合并,去重(command 相同视为同 hook,只跑一次)。
- 非法正则:该 entry 跳过(诚实:不因坏 matcher 卡 agent)。"""
from __future__ import annotations

import re
from typing import Iterable

from argos_agent.hooks.config import HookHandler, HookMatcherEntry, HooksConfig

# PreToolUse / PostToolUse 用 matcher;其他事件忽略 matcher 字段
_MATCHER_USED_EVENTS: frozenset[str] = frozenset({"PreToolUse", "PostToolUse"})


def _matcher_hits(matcher: str | None, tool_names: Iterable[str]) -> bool:
    """matcher 正则(可空)对 tool_names 任一命中即 True。
    matcher 为 None / 空字符串 / '*' → 全匹配(spec §2.2)。"""
    if matcher is None or matcher == "" or matcher == "*":
        return True
    try:
        pat = re.compile(matcher)
    except re.error:
        return False   # 非法正则:不命中(由 match() 整 entry 跳过)
    return any(pat.search(name) for name in tool_names)


def match(
    event_name: str,
    tool_names: Iterable[str],
    config: HooksConfig,
) -> list[HookHandler]:
    """按 event_name + tool_names 找出所有应触发的 HookHandler(去重)。

    Returns:
        去重后的 HookHandler 列表(按出现顺序)。空 config / 不命中 → 空列表。
    """
    entries = config.entries.get(event_name, ())
    use_matcher = event_name in _MATCHER_USED_EVENTS
    seen_commands: set[str] = set()
    result: list[HookHandler] = []
    tool_list = list(tool_names)   # 物化一次(避免多次迭代)
    for entry in entries:
        # 非 Pre/Post 事件:忽略 matcher,所有 entry 的 hooks 都进
        # Pre/Post 事件:matcher 必须命中
        if use_matcher and not _matcher_hits(entry.matcher, tool_list):
            continue
        for h in entry.hooks:
            if h.command in seen_commands:
                continue
            seen_commands.add(h.command)
            result.append(h)
    return result
