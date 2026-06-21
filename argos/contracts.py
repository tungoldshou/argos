"""契约层 —— Argos 唯一有实测数据(MiniMax 上结构化任务冲突 8→0)的差异化资产。

从旧 TS contracts.ts 移植。核心思想:对【结构化工程任务】(REST API / DB schema /
状态机 / 配置),给便宜模型一份覆盖完整的"必检约定 checklist",逼它把会打架的形式约定
(命名/类型/时区/枚举vs布尔/并发令牌/封装/长度/对齐自检)显式定死,从"拼不起来"变成
"零冲突可组装"。

边界(已实测):只对结构化工程任务有效;对开放式写作/分析无效甚至有害(15>10)。所以
domain 判定为非结构化时,【不注入契约】,退回裸 agent。

在 Python agent 里的用法:任务被判为某结构化领域时,把对应契约模板拼进 system_prompt,
约束 agent 的产出对齐。
"""
from __future__ import annotations

import re
from typing import Literal

Domain = Literal["rest-api", "db-schema", "state-machine", "config", "generic", "none"]

# ── 各领域的"必检约定"骨架(便宜模型会漏的形式约定 = 护城河知识)──────────────
REST_API = """[C1] Primary key id type and format (e.g. string/UUIDv4)
[C2] JSON field naming convention (snake_case or camelCase — globally consistent)
[C3] Timestamp field names and format (field name, type, timezone — e.g. created_at/updated_at, ISO 8601 UTC Z)
[C4] Status/completion flag: choose exactly one of enum field vs. boolean field; the other is forbidden
[C5] The chosen field from [C4]: persisted in the data model; if enum, all valid values listed and accepted by every write endpoint
[C6] Optimistic concurrency token field name; persisted in the data model, validated on writes; status code on conflict
[C7] Unified response envelope: format for single-item and list responses (including status/error code fields; envelope fields must not be persisted)
[C8] Error format (exactly one structure, containing a numeric code and a message)
[C9] Maximum field length limits; status code when a value exceeds the limit
[C10] Interface-to-data-model alignment check: for every endpoint, verify that its request/response field set matches the data model field set — no dangling references"""

DB_SCHEMA = """[D1] Table and column naming convention (globally consistent)
[D2] Primary key strategy (auto-increment BIGINT / UUID / ULID — consistent across all tables)
[D3] Foreign key naming convention; foreign key type must exactly match the referenced primary key type
[D4] Timestamp columns (column name, type such as TIMESTAMPTZ, timezone — consistent across all tables)
[D5] Soft-delete strategy (deleted_at column vs. hard delete; if used, all queries must filter on it)
[D6] Monetary/precision type (NUMERIC(p,s) or integer cents; FLOAT is forbidden for money)
[D7] Enum storage strategy (CHECK constraint / lookup table / native ENUM — exactly one approach)
[D8] String length limits and character set
[D9] Cross-table referential integrity check: for every foreign key (child_table.col → parent_table.col), verify type consistency, parent table is created first, and there are no cycles"""

STATE_MACHINE = """[S1] Complete state set (exhaustively listed, globally unique names)
[S2] Event/action naming convention (consistent tense)
[S3] Initial state and set of terminal states
[S4] Valid transition table: (current_state, event) → new_state, exhaustively enumerated
[S5] Invalid transition handling (error type and status code to return — consistent)
[S6] Idempotency: behavior when the same event is triggered again (ignore / error / replay — consistent)
[S7] Guard/precondition naming and semantics
[S8] Transition closure check: every non-terminal state has a defined response (transition or explicit rejection) for every event"""

CONFIG = """[F1] Key naming convention (globally consistent)
[F2] Nesting structure convention (by module or by environment — consistent)
[F3] Type and unit for booleans, numbers, and durations (e.g. durations uniformly in seconds or "30s")
[F4] How default values are annotated
[F5] Environment variable override rules (prefix, case, precedence)
[F6] Secret/sensitive key handling (plaintext is forbidden)
[F7] Key namespace check: no duplicate keys with different meanings, no structural hierarchy conflicts"""

GENERIC = """[G1] Identifier naming convention (globally consistent)
[G2] Data type, format, and unit for all key fields
[G3] Date/time representation (consistent format and timezone)
[G4] Enum/status values (exhaustively listed, consistently named)
[G5] Error/exception representation (exactly one structure)
[G6] Cross-module interface alignment check: every output's public contract (fields / signatures / data shapes) is type-consistent, has no dangling references, and has no naming collisions"""

_TEMPLATES: dict[str, tuple[str, str]] = {
    "rest-api": ("REST API", REST_API),
    "db-schema": ("Database Schema", DB_SCHEMA),
    "state-machine": ("State Machine", STATE_MACHINE),
    "config": ("Config", CONFIG),
    "generic": ("Generic", GENERIC),
}

# 关键词分类(0 成本兜底)。命中多个按 rest>schema>状态机>config 优先。
_KEYWORDS: list[tuple[Domain, re.Pattern]] = [
    ("rest-api", re.compile(r"\b(rest|api|endpoint|http|route)\b|端点|接口|路由", re.I)),
    ("db-schema", re.compile(r"\b(schema|table|migration|ddl|orm|foreign\s*key)\b|数据库|表结构|外键|建表|迁移", re.I)),
    ("state-machine", re.compile(r"\b(state\s*machine|fsm|workflow)\b|状态机|状态流转|流转|工作流|审批流", re.I)),
    ("config", re.compile(r"\b(config|yaml|toml|settings|feature\s*flag)\b|\.env|配置|参数文件", re.I)),
]

# 非结构化信号(写作/分析)——命中则【不注入契约】(实测契约有害)。
_NON_STRUCTURED = re.compile(
    r"\b(write|essay|article|blog|story|summary|analy|review|compare|opinion)\b"
    r"|写一?篇|文章|博客|故事|总结|分析|评论|横评|观点|心得",
    re.I,
)


def classify(goal: str) -> Domain:
    """判定目标的契约领域。非结构化(写作/分析)→ 'none'(不注入契约)。
    纯关键词,0 成本;LLM 语义分类是可选增强,这里先用兜底(够用且不烧 token)。"""
    if _NON_STRUCTURED.search(goal):
        return "none"
    for dom, pat in _KEYWORDS:
        if pat.search(goal):
            return dom
    # 含明显工程信号词才当 generic 结构化,否则也不强加契约。
    if re.search(r"\b(function|class|interface|type|json|model|field|enum)\b|函数|类|字段|模型|类型|枚举", goal, re.I):
        return "generic"
    return "none"


def contract_for(goal: str) -> tuple[Domain, str | None]:
    """返回 (领域, 契约约束文本或None)。None=非结构化,不注入。"""
    dom = classify(goal)
    if dom == "none":
        return dom, None
    label, body = _TEMPLATES[dom]
    text = (
        f"\n\n[Structured Engineering Task ({label})] Before writing any code, you MUST lock down "
        f"each of the following formal conventions one by one — globally consistent, no ambiguity. "
        f"This ensures all outputs are directly composable and eliminates field/type/naming conflicts:\n{body}\n"
        f"State these conventions explicitly in your output first, then implement."
    )
    return dom, text


def all_domains() -> list[tuple[str, str]]:
    """(领域id, 显示名) 列表,供 UI 展示覆盖范围。"""
    return [(k, v[0]) for k, v in _TEMPLATES.items()]
