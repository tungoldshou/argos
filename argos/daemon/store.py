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
        # #5 集中领号:per-run 最新 _seq(内存缓存);首次 append 某 run 时从文件恢复 max,
        # 保证跨 daemon 重启单调延续(否则 resume 后 _seq 回退,客户端 SSE 游标错乱)。
        self._seq: dict[str, int] = {}

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

    def append(self, run_id: str, event: dict[str, Any]) -> int:
        """追加一行 JSON(spec §2.4 写约束);返回该事件分配的 _seq(run_meta 返 0,不领号)。

        - #5 集中领号:worker 与 manager(state_change/checkpoint)两条写入路径都经此,
          每个非 meta 事件领唯一单调 _seq → replay 按 _seq 字段过滤,客户端续传不错位。
        - run_meta 触发 fsync(directory entry 落盘,断电可恢复)
        - 其余事件仅 open(append) 写;PIPE_BUF 限制下 <4KB 行原子
        """
        path = self._path_for(run_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        is_meta = event.get("kind") == "run_meta"
        seq = 0
        if not is_meta:
            seq = self._next_seq(run_id)
            event["_seq"] = seq
        line = json.dumps(event, ensure_ascii=False, separators=(",", ":")) + "\n"
        with path.open("a", encoding="utf-8") as fh:
            fh.write(line)
            if is_meta:
                fh.flush()
                os.fsync(fh.fileno())
        return seq

    def _next_seq(self, run_id: str) -> int:
        """分配下一个单调 _seq(per-run)。内存计数器缺失(daemon 重启)时从文件恢复 max。"""
        cur = self._seq.get(run_id)
        if cur is None:
            cur = self._max_seq_in_file(run_id)
        nxt = cur + 1
        self._seq[run_id] = nxt
        return nxt

    def _max_seq_in_file(self, run_id: str) -> int:
        """扫已落盘文件取最大 _seq(每 run 首次 append 调一次,跨重启单调延续)。"""
        path = self._path_for(run_id)
        if not path.exists():
            return 0
        m = 0
        with path.open("r", encoding="utf-8") as fh:
            for raw in fh:
                raw = raw.strip()
                if not raw:
                    continue
                try:
                    ev = json.loads(raw)
                except json.JSONDecodeError:
                    continue
                s = ev.get("_seq") if isinstance(ev, dict) else None
                if isinstance(s, int) and s > m:
                    m = s
        return m

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
                # 非 meta:按事件 _seq 字段过滤(与客户端游标一致;集中领号后每事件有唯一 _seq)。
                ev_seq = ev.get("_seq")
                if ev_seq is None:
                    # 历史文件/改动前写的事件无 _seq:全量重放(since<=0)yield 不漏;增量续传跳过
                    # (无游标无法精确定位;新数据所有事件均领号,不会走此分支)。
                    if since_seq <= 0:
                        yield ev
                    continue
                if ev_seq > since_seq:
                    yield ev

    def last_state(self, run_id: str) -> str | None:
        """从 JSONL tail 找最近 state_change 的 to 字段;无 state_change → None。"""
        last: str | None = None
        for ev in self.replay(run_id):
            if ev.get("kind") == "state_change":
                last = ev.get("to")
        return last

    def last_checkpoint(self, run_id: str) -> dict[str, Any] | None:
        """返回最近一条 run_checkpoint 事件 dict;无则 None(用于 resume-from-suspended 恢复)。"""
        last: dict[str, Any] | None = None
        for ev in self.replay(run_id):
            if ev.get("kind") == "run_checkpoint":
                last = ev
        return last
