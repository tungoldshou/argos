"""argos_agent.perception — OS 级计算机感知与控制(P6a §10)。

公开接口:
  ComputerAction        — 冻结动作值对象(actions.py)
  ComputerActionResult  — 执行结果值对象(executor.py)
  ComputerExecutor      — 零依赖 macOS 后端(executor.py)

能力开关:ARGOS_COMPUTER_USE=1(默认关)。
"""
from argos_agent.perception.actions import ComputerAction, ActionKind, TEXT_MAX_LEN
from argos_agent.perception.executor import ComputerExecutor, ComputerActionResult

__all__ = [
    "ComputerAction",
    "ActionKind",
    "TEXT_MAX_LEN",
    "ComputerExecutor",
    "ComputerActionResult",
]
