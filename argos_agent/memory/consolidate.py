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
        # merged_losers:同 key 异 value 的被淘汰 older —— 永不硬删,随 to_archive 一起归档。
        # 纯重复(同 value)无信息丢失,不入此列;但 use_count 仍累加(见下)。
        merged_losers: list[dict] = []
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
                # 同 key 合并:内容取 ts 新的;活跃度(use_count/last_used_at/confidence)聚合。
                newer, older = (
                    (e, prev)
                    if float(e.get("ts", 0)) >= float(prev.get("ts", 0))
                    else (prev, e)
                )
                newer = dict(newer)
                # use_count 累加(频次相加)
                newer["use_count"] = int(newer.get("use_count", 0)) + int(older.get("use_count", 0))
                # last_used_at / confidence 用 max 聚合:合并不该让"最近用过 / 更可信"的信号退化,
                # 否则 survivor 可能因 ts-新那条恰好久未使用而被误判衰减归档(review#3)。
                newer["last_used_at"] = max(
                    float(newer.get("last_used_at", newer.get("ts", 0))),
                    float(older.get("last_used_at", older.get("ts", 0))),
                )
                newer["confidence"] = max(
                    float(newer.get("confidence", 0.5)),
                    float(older.get("confidence", 0.5)),
                )
                by_key[k] = newer
                # older 永不硬删:value 不同则归档(保留被淘汰内容);同 value 是纯重复,无需归档。
                if older.get("value") != newer.get("value"):
                    merged_losers.append(older)
                file_merged += 1
        survivors: list[dict] = []
        for e in by_key.values():
            if _score(e, now) < archive_threshold:
                to_archive.append(e)
            else:
                survivors.append(e)
        if file_merged == 0 and not to_archive:
            continue  # 无变化不重写
        # 衰减归档 + 合并淘汰的 older(异 value)同批写入归档区,统一"永不硬删"。
        archive_batch = to_archive + merged_losers
        try:
            # 先追加归档(归档成功才允许从源移除 —— 宁可重复不可丢失)
            if archive_batch:
                with archive_path.open("a", encoding="utf-8") as af:
                    for e in archive_batch:
                        af.write(json.dumps(e, ensure_ascii=False) + "\n")
            new_lines = keep_raw + [json.dumps(e, ensure_ascii=False) for e in survivors]
            tmp = f.with_suffix(".jsonl.tmp")
            tmp.write_text(
                "\n".join(new_lines) + ("\n" if new_lines else ""),
                encoding="utf-8",
            )
            tmp.replace(f)
            merged += file_merged
            # archived 计数包含合并淘汰的 older:语义=本轮落进 archive.jsonl 的条目数
            # (诚实反映归档区实际增量,既含衰减归档也含合并归档)。
            archived += len(archive_batch)
            touched += 1
        except Exception as e:  # noqa: BLE001
            log.warning("consolidate: 重写失败 %s: %s", f, e)
            errors += 1
    return ConsolidationReport(merged=merged, archived=archived,
                               files_touched=touched, errors=errors)
