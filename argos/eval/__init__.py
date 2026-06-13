"""#7 Agent eval / 用户项目级 A/B 自我评估子包。

- corpus.py:任务清单 + 解析
- runner.py:EvalRunner.run() 核心
- results.py:JSONL 持久化 + list/load/summary
- compare.py:A/B run_pair + 报告生成
- cli (in argos/cli/eval.py):argos eval 子命令
"""
from __future__ import annotations

__all__ = ["corpus", "runner", "results", "compare"]
