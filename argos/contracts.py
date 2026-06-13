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
REST_API = """[C1] 主键 id 的类型与格式(如 string/UUIDv4)
[C2] JSON 字段命名风格(snake_case 或 camelCase,全局统一)
[C3] 时间字段命名与格式(字段名、类型、时区,如 created_at/updated_at, ISO8601 UTC Z)
[C4] 状态/完成标志:枚举字段 与 布尔字段 只选一个,另一个禁用
[C5] 上条选定字段:数据模型持久化它;若枚举则列全取值且所有写端点接受
[C6] 并发控制令牌字段名;数据模型持久化、写操作校验;冲突时状态码
[C7] 统一响应封装:单条/列表格式(含状态/错误码字段,封装字段不进持久层)
[C8] 错误格式(统一一种,含数字 code 与 message)
[C9] 字段长度上限;超长状态码
[C10] 接口-数据模型对齐自检:每个端点的请求/响应字段集 + 数据模型字段集,确认无悬空"""

DB_SCHEMA = """[D1] 表/列命名风格(全局统一)
[D2] 主键策略(自增BIGINT / UUID / ULID,所有表统一)
[D3] 外键命名约定,且类型与被引用主键完全一致
[D4] 时间戳列(列名、类型如 TIMESTAMPTZ、时区,所有表统一)
[D5] 软删除策略(deleted_at 还是物理删除;若用,所有查询过滤)
[D6] 金额/精度类型(NUMERIC(p,s) 或整数分,禁 FLOAT 存钱)
[D7] 枚举落库方式(CHECK / 枚举表 / 原生 ENUM,统一一种)
[D8] 字符串长度与字符集
[D9] 跨表引用完整性自检:每个外键(子表.列→父表.列)类型一致、父表先建、无环"""

STATE_MACHINE = """[S1] 状态集合(完整列出,全局唯一命名)
[S2] 事件/动作命名(时态统一)
[S3] 初始状态、终止状态集
[S4] 合法转移表:(当前状态,事件)→新状态,穷举
[S5] 非法转移处理(返回什么错误/状态码,统一)
[S6] 幂等性:同事件重复触发的行为(忽略/报错/重放,统一)
[S7] 守卫/前置条件命名与语义
[S8] 转移闭合性自检:每个非终止状态对每个事件都有定义(转移或显式拒绝)"""

CONFIG = """[F1] 键命名风格(全局统一)
[F2] 嵌套层级约定(按模块/按环境,统一)
[F3] 布尔/数值/时长的类型与单位(如时长统一秒还是 "30s")
[F4] 默认值标注方式
[F5] 环境变量覆盖规则(前缀、大小写、优先级)
[F6] 密钥/敏感项处理(禁明文)
[F7] 键命名空间自检:无同名异义键、无层级冲突"""

GENERIC = """[G1] 标识符命名风格(全局统一)
[G2] 关键字段的数据类型与格式、单位
[G3] 时间/日期表示(统一格式与时区)
[G4] 枚举/状态取值(完整列出,统一命名)
[G5] 错误/异常表示(统一一种结构)
[G6] 模块间接口对齐自检:各产出的对外契约(字段/签名/数据形状)类型一致、无悬空、无重名"""

_TEMPLATES: dict[str, tuple[str, str]] = {
    "rest-api": ("REST API", REST_API),
    "db-schema": ("数据库 Schema", DB_SCHEMA),
    "state-machine": ("状态机", STATE_MACHINE),
    "config": ("配置文件", CONFIG),
    "generic": ("通用结构化", GENERIC),
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
        f"\n\n【结构化工程任务({label})—— 必须先把下列形式约定逐条定死再写代码,"
        f"全局统一、不留歧义,这能让产出可直接组装、避免字段/类型/命名打架】:\n{body}\n"
        f"先在产出里明确这些约定,再实现。"
    )
    return dom, text


def all_domains() -> list[tuple[str, str]]:
    """(领域id, 显示名) 列表,供 UI 展示覆盖范围。"""
    return [(k, v[0]) for k, v in _TEMPLATES.items()]
