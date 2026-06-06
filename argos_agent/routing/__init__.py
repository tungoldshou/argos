"""Per-task model routing(契约 §11;spec #11)。

公开 surface:TaskCategory 枚举 + categorize() 函数(其他模块按需懒 import)。
"""
from argos_agent.routing.categorizer import TaskCategory, categorize

__all__ = ["TaskCategory", "categorize"]
