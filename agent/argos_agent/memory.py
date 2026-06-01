"""记忆持久化:agent 跑完任务,把记录沉淀到本地 JSONL。

这是 Argos 的"记忆大脑"数据源 —— 真实的、随任务生长的记忆,不是编造的演示数据。
每条记录是 agent 跑完的一个任务:目标 + verify 裁决 + 模型 + 时间。

刻意极简:一个 append-only JSONL 文件,无数据库依赖。读时按时间倒序、限量返回。
位置 ~/.argos/memory.jsonl(可被 ARGOS_MEMORY_FILE 覆盖,测试用)。
"""
from __future__ import annotations

import json
import os
import time
import uuid
from pathlib import Path


def _memory_file() -> Path:
    override = os.environ.get("ARGOS_MEMORY_FILE")
    if override:
        return Path(override)
    return Path.home() / ".argos" / "memory.jsonl"


def record_task(goal: str, verdict: str | None = None, model: str | None = None,
                fact: str | None = None) -> dict:
    """追加一条任务记忆。返回写入的记录(含生成的 id/ts)。"""
    rec = {
        "id": uuid.uuid4().hex[:12],
        "goal": goal,
        "verdict": verdict,
        "model": model,
        "fact": fact,
        "ts": time.time(),
    }
    f = _memory_file()
    f.parent.mkdir(parents=True, exist_ok=True)
    with f.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
    return rec


def load_memories(limit: int = 200) -> list[dict]:
    """读取记忆,按时间倒序,最多 limit 条。文件不存在 → 空列表(诚实空态)。"""
    f = _memory_file()
    if not f.exists():
        return []
    out: list[dict] = []
    for line in f.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue  # 跳过损坏行,不让一行坏数据毁掉整个记忆
    out.sort(key=lambda r: r.get("ts") or 0, reverse=True)
    return out[:limit]
