"""RunStore:JSONL append-only 持久化层(spec §2.3 + §2.4)。

- append(run_id, event_dict) → 写一行 JSON;run_meta 走 fsync(directory entry 落盘)
- replay(run_id, since_seq=0) → yield 每行 dict;坏行跳过 + log warning
- corruption:replay 第一个非空行必须 kind=run_meta(否则报 CorruptionError)

复刻 spec §2.3 / §2.4 字段 + 写约束。"""
from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any, Iterator

log = logging.getLogger(__name__)


class CorruptionError(Exception):
    """RunStore 持久化文件 corruption(首行非 run_meta / 文件结构破坏)。"""


class RunStore:
    """JSONL append-only store(每 run 一文件)。"""

    def __init__(self, runs_dir: Path):
        self._dir = Path(runs_dir)
        self._dir.mkdir(parents=True, exist_ok=True)

    @property
    def runs_dir(self) -> Path:
        return self._dir

    def _path_for(self, run_id: str) -> Path:
        return self._dir / f"{run_id}.jsonl"

    def exists(self, run_id: str) -> bool:
        return self._path_for(run_id).exists()

    def list_runs(self) -> list[str]:
        """列出所有 run_id(扫描 .jsonl 文件)。"""
        if not self._dir.exists():
            return []
        return sorted(p.stem for p in self._dir.glob("*.jsonl"))

    def append(self, run_id: str, event: dict[str, Any]) -> None:
        """追加一行 JSON(spec §2.4 写约束)。

        - run_meta 触发 fsync(directory entry 落盘,断电可恢复)
        - 其余事件仅 open(append) 写;PIPE_BUF 限制下 <4KB 行原子
        """
        path = self._path_for(run_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        line = json.dumps(event, ensure_ascii=False, separators=(",", ":")) + "\n"
        with path.open("a", encoding="utf-8") as fh:
            fh.write(line)
            if event.get("kind") == "run_meta":
                fh.flush()
                os.fsync(fh.fileno())

    def replay(
        self,
        run_id: str,
        since_seq: int = 0,
    ) -> Iterator[dict[str, Any]]:
        """重放事件流(spec §2.4 读契约)。

        - since_seq=0:从 run_meta 开始 yield
        - since_seq=N:跳过前 N 个非 meta 事件
        - 坏 JSONL 行 → log.warning + 跳过(不抛)
        - 文件不存在 → 无 yield
        """
        path = self._path_for(run_id)
        if not path.exists():
            return
        seq = 0
        meta_seen = False
        with path.open("r", encoding="utf-8") as fh:
            for raw in fh:
                raw = raw.rstrip("\n").rstrip("\r")
                if not raw:
                    continue
                try:
                    ev = json.loads(raw)
                except json.JSONDecodeError as e:
                    log.warning("RunStore.replay: corrupt line in %s: %s (skipping)", path, e)
                    continue
                if not isinstance(ev, dict):
                    log.warning("RunStore.replay: non-dict line in %s (skipping)", path)
                    continue
                if not meta_seen:
                    if ev.get("kind") != "run_meta":
                        raise CorruptionError(
                            f"first line of {path} is not run_meta: {ev.get('kind')!r}"
                        )
                    meta_seen = True
                    yield ev
                    continue
                # 非 meta:走 since_seq 过滤
                if seq >= since_seq:
                    yield ev
                seq += 1

    def last_state(self, run_id: str) -> str | None:
        """从 JSONL tail 找最近 state_change 的 to 字段;无 state_change → None。"""
        last: str | None = None
        for ev in self.replay(run_id):
            if ev.get("kind") == "state_change":
                last = ev.get("to")
        return last
