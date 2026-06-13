"""Hook matcher 逻辑(spec §2.2 / §4.2 / D14)。

- Pre/Post 事件:matcher 正则(可选)匹 `tool_names`;空 / `*` / None = 全匹配。
- 其他事件(Stop / UserPromptSubmit / SessionStart):忽略 matcher,所有 entry 的 hooks 返。
- 同事件多 entry 合并,去重(command 相同视为同 hook,只跑一次)。
- 加载期校验(`validate_matcher`,spec D14):长度 > 256 / 嵌套量词 / 编译失败 → 整 entry
  拒载(`HooksConfigError`,与 D11 一致:整配失败 ≠ 部分加载)。运行时
  `_matcher_hits` 仍保 try/except 兜底,防止手动构造的 entry 爆。"""
from __future__ import annotations

import re
from typing import Iterable

from argos.hooks.config import (
    HookHandler,
    HookMatcherEntry,
    HooksConfig,
    HooksConfigError,
)

# PreToolUse / PostToolUse 用 matcher;其他事件忽略 matcher 字段
_MATCHER_USED_EVENTS: frozenset[str] = frozenset({"PreToolUse", "PostToolUse"})

# matcher 长度上限(spec D14):防 1MB 正则爆 re 模块
MAX_MATCHER_LENGTH: int = 256

# ReDoS 危险模式启发式:嵌套量词(...,)+/(...)* 形式。
# 例:`(.*)*` / `(.+)+` / `(\w+)*` / `(.+\1+)` 等。简单 r"..." 文字/单层量词不算。
# 注释:D14 spec 描述为"嵌套量词 / 回溯危险模式";re2 / pyre2 才需
# 完备分析,本项目用 re,所以启发式足够——出现 1 次就拒载,真出现时让用户改写。
_NESTED_QUANTIFIER_RE: re.Pattern[str] = re.compile(
    r"\([^)]*[+*][^)]*\)\s*[+*]"   # 形如 ( ... +| * ) ... +| *
)


def validate_matcher(matcher: str) -> None:
    """加载期校验 matcher 字段(spec D14)。失败 → `HooksConfigError`(整配拒载)。

    校验项:
    1. 长度 ≤ 256 字符(防 1MB 正则爆 re 模块)
    2. 无嵌套量词(ReDoS 危险:`(.*)*` / `(.+)+$` 等)
    3. `re.compile(matcher)` 不抛(捕获 `re.error`)

    Args:
        matcher: 非空 matcher 字符串(已通过 type 校验)。空串 / `*` 由调用方处理,
            此函数不负责"语义化"。

    Raises:
        HooksConfigError: 任一校验项失败。
    """
    if len(matcher) > MAX_MATCHER_LENGTH:
        raise HooksConfigError(
            f"matcher 长度 {len(matcher)} > {MAX_MATCHER_LENGTH}(spec D14 上限)"
        )
    if _NESTED_QUANTIFIER_RE.search(matcher):
        raise HooksConfigError(
            f"matcher {matcher!r} 含嵌套量词(ReDoS 危险模式,spec D14):"
            f"形如 (.*)* / (.+)+ 等"
        )
    try:
        re.compile(matcher)
    except re.error as e:
        raise HooksConfigError(
            f"matcher {matcher!r} 编译失败(re.error): {e}"
        ) from e


def _matcher_hits(matcher: str | None, tool_names: Iterable[str]) -> bool:
    """matcher 正则(可空)对 tool_names 任一命中即 True。
    matcher 为 None / 空字符串 / '*' → 全匹配(spec §2.2)。
    matcher 非法正则(构造期未校验):返回 False,该 entry 跳过(兜底)。"""
    if matcher is None or matcher == "" or matcher == "*":
        return True
    try:
        pat = re.compile(matcher)
    except re.error:
        return False   # 兜底:加载期已 validate_matcher,这里不会到
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
