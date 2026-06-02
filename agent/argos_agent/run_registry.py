"""run 的持久档案(sqlite)——恢复的唯一信息源。

内存 SESSIONS 重启即失;registry 不失。resume 时从这里重建 RunContext(workspace/
verify_dir/project_mode/guard/verify_cmd)、配 thread_id 续 checkpoint。每次操作新开连接
(短事务),省心、天然跨连接(=跨重启)持久。
"""
from __future__ import annotations

import json
import os
import sqlite3
import time
from pathlib import Path

REGISTRY_PATH = Path(os.environ.get("ARGOS_RUN_DB", Path.home() / ".argos" / "runs.db"))

_SCHEMA = """CREATE TABLE IF NOT EXISTS runs(
    run_id TEXT PRIMARY KEY, session_id TEXT, thread_id TEXT,
    workspace TEXT, verify_dir TEXT, project_dir TEXT, project_mode INTEGER,
    guard TEXT, goal TEXT, verify_cmd TEXT, status TEXT, created REAL, updated REAL)"""


def _conn() -> sqlite3.Connection:
    REGISTRY_PATH.parent.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(str(REGISTRY_PATH))
    c.execute(_SCHEMA)
    return c


def open_run(*, run_id: str, session_id: str, thread_id: str, workspace, verify_dir,
             project_dir: str | None, project_mode: bool, guard: list[str] | None,
             goal: str, verify_cmd: str | None) -> None:
    now = time.time()
    with _conn() as c:
        c.execute(
            "INSERT OR REPLACE INTO runs VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (run_id, session_id, thread_id, str(workspace), str(verify_dir),
             project_dir or "", int(bool(project_mode)), json.dumps(guard or []),
             goal, verify_cmd or "", "running", now, now),
        )


def mark(run_id: str, status: str) -> None:
    with _conn() as c:
        c.execute("UPDATE runs SET status=?, updated=? WHERE run_id=?",
                  (status, time.time(), run_id))


def get(run_id: str) -> dict | None:
    with _conn() as c:
        cur = c.execute("SELECT * FROM runs WHERE run_id=?", (run_id,))
        row = cur.fetchone()
        cols = [d[0] for d in cur.description]
    if not row:
        return None
    d = dict(zip(cols, row))
    d["guard"] = json.loads(d["guard"] or "[]")
    d["project_mode"] = bool(d["project_mode"])
    d["verify_cmd"] = d["verify_cmd"] or None
    return d
