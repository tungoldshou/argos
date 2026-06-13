"""Conductor — 自治调度核心（设计 §9 自治面）。

「主动建议永远要用户确认，建议不擅自执行。」

公开 API：
  StandingOrder       常驻指令 frozen dataclass
  OrderStore          JSONL 持久化 CRUD
  next_due            cron-lite 下次触发时间计算
  FileTriggerWatcher  mtime 轮询文件触发器
  FileTriggerFact     触发事实 frozen dataclass
  ProactiveSuggestion 主动建议 frozen dataclass（requires_confirmation 恒 True）
  propose             StandingOrder + context → ProactiveSuggestion
  ConductorEngine     tick() 驱动自治调度引擎
"""
from argos.conductor.orders import StandingOrder, OrderStore
from argos.conductor.cronlite import next_due
from argos.conductor.triggers import FileTriggerWatcher, FileTriggerFact
from argos.conductor.proposals import ProactiveSuggestion, propose
from argos.conductor.engine import ConductorEngine

__all__ = [
    "StandingOrder",
    "OrderStore",
    "next_due",
    "FileTriggerWatcher",
    "FileTriggerFact",
    "ProactiveSuggestion",
    "propose",
    "ConductorEngine",
]
