"""consolidate:记忆整理(Dream 夜间整合 phase ④)。

纪律:
- 永不硬删:衰减条目移入 <root>/archive.jsonl;
- 看不懂的行(坏 JSON)原样保留 —— 不动不属于自己的数据;
- 原子重写(tmp+replace);任何文件失败只记数,绝不抛。
"""
from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass
from pathlib import Path

log = logging.getLogger(__name__)

ARCHIVE_NAME = "archive.jsonl"
DEFAULT_ARCHIVE_THRESHOLD = 0.2


@dataclass(frozen=True, slots=True)
class ConsolidationReport:
    """一次整理的结果计数。"""
    merged: int = 0
    archived: int = 0
    files_touched: int = 0
    errors: int = 0


def _score(e: dict, now: float) -> float:
    """衰减打分:复用 auto.decayed_confidence(单一公式来源,绝不写第二份)。"""
    try:
        from argos_agent.memory.auto import decayed_confidence
        conf = float(e.get("confidence", 0.5))
        last = float(e.get("last_used_at", e.get("ts", now)))
        days = max(0.0, (now - last) / 86400.0)
        return decayed_confidence(conf, days)
    except Exception as e:  # noqa: BLE001 — 算不出分 = 不归档(保守)
        log.warning("consolidate: _score 失败,保守不归档: %s", e)
        return 1.0


def consolidate(
    memory_dir: Path, *, now: float | None = None,
    archive_threshold: float = DEFAULT_ARCHIVE_THRESHOLD,
) -> ConsolidationReport:
    """整理 memory_dir 下所有 tier JSONL(递归;跳过 archive.jsonl)。"""
    now = time.time() if now is None else now
    merged = archived = touched = errors = 0
    archive_path = memory_dir / ARCHIVE_NAME
    if not memory_dir.exists():
        return ConsolidationReport()

    for f in sorted(memory_dir.rglob("*.jsonl")):
        if f.name == ARCHIVE_NAME:
            continue
        try:
            raw_lines = f.read_text(encoding="utf-8").splitlines()
        except (OSError, UnicodeDecodeError) as e:
            log.warning("consolidate: 读失败 %s: %s", f, e)
            errors += 1
            continue
        keep_raw: list[str] = []      # 坏行原样保留
        by_key: dict[str, dict] = {}  # key → 最新条目(合并)
        to_archive: list[dict] = []
        file_merged = 0
        for line in raw_lines:
            line = line.strip()
            if not line:
                continue
            try:
                e = json.loads(line)
                assert isinstance(e, dict) and "key" in e
            except Exception:  # noqa: BLE001 — 看不懂的行原样保留
                keep_raw.append(line)
                continue
            k = str(e["key"])
            prev = by_key.get(k)
            if prev is None:
                by_key[k] = e
            else:
                # 同 key 重复:留 ts 新的,use_count 累加
                newer, older = (
                    (e, prev)
                    if float(e.get("ts", 0)) >= float(prev.get("ts", 0))
                    else (prev, e)
                )
                newer = dict(newer)
                newer["use_count"] = int(newer.get("use_count", 0)) + int(older.get("use_count", 0))
                by_key[k] = newer
                file_merged += 1
        survivors: list[dict] = []
        for e in by_key.values():
            if _score(e, now) < archive_threshold:
                to_archive.append(e)
            else:
                survivors.append(e)
        if file_merged == 0 and not to_archive:
            continue  # 无变化不重写
        try:
            # 先追加归档(归档成功才允许从源移除 —— 宁可重复不可丢失)
            if to_archive:
                with archive_path.open("a", encoding="utf-8") as af:
                    for e in to_archive:
                        af.write(json.dumps(e, ensure_ascii=False) + "\n")
            new_lines = keep_raw + [json.dumps(e, ensure_ascii=False) for e in survivors]
            tmp = f.with_suffix(".jsonl.tmp")
            tmp.write_text(
                "\n".join(new_lines) + ("\n" if new_lines else ""),
                encoding="utf-8",
            )
            tmp.replace(f)
            merged += file_merged
            archived += len(to_archive)
            touched += 1
        except Exception as e:  # noqa: BLE001
            log.warning("consolidate: 重写失败 %s: %s", f, e)
            errors += 1
    return ConsolidationReport(merged=merged, archived=archived,
                               files_touched=touched, errors=errors)
