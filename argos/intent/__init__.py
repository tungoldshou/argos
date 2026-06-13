"""NL→Goal 意图引擎(设计 §7 + §2.4)。

人话层核心：把所有人的口语请求变成引擎能执行的 Goal，
并堵住"翻译错=源头偏航"盲区。

公开接口：
    IntentCard  —— 意图解析结果(frozen dataclass)
    IntentEngine —— 解析 + 回显确认
"""
from argos.intent.card import IntentCard
from argos.intent.engine import IntentEngine

__all__ = ["IntentCard", "IntentEngine"]
