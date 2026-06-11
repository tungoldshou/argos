"""行为账本 Ledger v1 (spec §6 信任面)。

「敢放手因为能反悔」的信任地基:把签名回执沉淀为人话可读、可回放、
可撤销(诚实三态)的行为账本。

公开 API:
  LedgerEntry   — 单条账本条目(frozen dataclass)
  LedgerStore   — JSONL 追加 + 回放
  summarize     — Receipt → 人话一句(确定性模板,0 成本,不调模型)
  build_entry   — Receipt → LedgerEntry(含人话 + 三态)
"""
from argos_agent.ledger.entry import LedgerEntry, UndoState, Reversible
from argos_agent.ledger.summary import summarize
from argos_agent.ledger.store import LedgerStore
from argos_agent.ledger.builder import build_entry

__all__ = [
    "LedgerEntry",
    "UndoState",
    "Reversible",
    "LedgerStore",
    "summarize",
    "build_entry",
]
