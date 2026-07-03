from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import Union

_log = logging.getLogger("argos.jsonl_log")

Payload = Union[dict, str]


def append_line(path: Path, payload: Payload, *, logger: logging.Logger | None = None) -> None:
    p = Path(path)
    lg = logger or _log
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(payload, dict):
            line = json.dumps(payload, ensure_ascii=False) + "\n"
        else:
            line = payload if payload.endswith("\n") else payload + "\n"
        with p.open("a", encoding="utf-8") as fh:
            fh.write(line)
    except OSError as e:
        lg.warning("jsonl_log: append 失败 %s: %s", p, e)


def cleanup_files_by_name_date(
    dir: Path, glob: str, *, prefix: str, days: int,
    now: datetime | None = None, logger: logging.Logger | None = None,
) -> int:
    d = Path(dir)
    if not d.exists():
        return 0
    lg = logger or _log
    cutoff = (now or datetime.now()) - timedelta(days=days)
    removed = 0
    try:
        for f in d.glob(glob):
            try:
                date_str = f.stem.replace(prefix, "", 1)
                file_date = datetime.strptime(date_str, "%Y-%m-%d")
            except ValueError:
                lg.warning("jsonl_log: cleanup 跳过无法解析的文件名 %s", f)
                continue
            if file_date < cutoff:
                try:
                    f.unlink()
                    removed += 1
                except OSError as e:
                    lg.warning("jsonl_log: cleanup %s 失败: %s", f, e)
    except OSError as e:
        lg.warning("jsonl_log: cleanup 扫描 %s 失败: %s", d, e)
    return removed
