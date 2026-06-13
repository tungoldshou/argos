"""IntentCard — 意图解析结果(设计 §7 + §2.4)。

frozen dataclass：可哈希、线程安全、适合事件系统传递。
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class IntentCard:
    """口语意图的规范化表示。

    字段说明：
        utterance           原始口语输入，原样保留。
        goal                规范化目标描述，喂给 AgentLoop.run() 的 user_goal 参数。
        deliverable         交付物形态的人话描述（"一个 Python 脚本" / "已发出的邮件"）。
        constraints         额外约束元组（"不要修改生产数据库"）。
        not_doing           明确不做事项元组（防止误解范围）。
        risk_flags          高风险 / 不可逆意图标签元组（"delete_files" / "send_email"）。
        confirmation_required  True → 执行前必须用户确认；False → 直出。
        questions           ≤3 个澄清问，只问改变方案的问题；空元组 = 无需澄清。
    """
    utterance: str
    goal: str
    deliverable: str = ""
    constraints: tuple[str, ...] = field(default_factory=tuple)
    not_doing: tuple[str, ...] = field(default_factory=tuple)
    risk_flags: tuple[str, ...] = field(default_factory=tuple)
    confirmation_required: bool = False
    questions: tuple[str, ...] = field(default_factory=tuple)
