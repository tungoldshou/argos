"""共享 best-effort JSONL 写入器(任务:audit / eval / memory 抽样板)。

设计要点:
- IO 失败 → log warning + 不抛(best-effort 语义);daemon/store.py 那种"必须抛"
  +fsync+行守卫模式【不抽】,本助手只服务"主流程不依赖磁盘日志"的场景。
- 不带锁(单进程 best-effort 写不要求跨进程锁;eval 已有自己的 threading.Lock,
  在助手外层包)。
- 不带 fsync(daemon 专属,其他不要)。
- append_line 接 dict 或 str(audit/memory 传 dict 助手内部 dumps;eval 传 str
  因为 payload 已是 result.to_json() 产物,助手直接 write + 换行)。
- ensure_ascii=False(三个 best-effort 用户都用 False,daemon 走紧凑 separators
  是不同模式,不在本助手)。

cleanup_files_by_name_date 按 audit 的 30 天清理抽(参数化 days + prefix + glob,
其他模块未来需要类似清理也能复用)。
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import Union

_log = logging.getLogger("argos.jsonl_log")

# payload 形态:dict 走 json.dumps,str 已是 JSON 字符串直接 write
Payload = Union[dict, str]


def append_line(path: Path, payload: Payload, *, logger: logging.Logger | None = None) -> None:
    """append 一行 JSON 到 path。IO 失败 → log warning + 不抛。

    Args:
        path: 目标 jsonl 文件路径(目录不存在会自动建)。
        payload: dict → 助手内部 json.dumps(ensure_ascii=False) 写;
                 str → 助手直接 write(假设已是 JSON 字符串,如 eval 的 to_json 产物)。
        logger: 自定义 logger;None 用模块级 _log。

    行为契约(与 audit / eval / memory 旧实现一致):
    - 目录不存在 → mkdir(parents=True, exist_ok=True)
    - open(path, "a", encoding="utf-8") + write(line + "\\n")(若 str 无结尾 \\n 自动补)
    - 任何 OSError → log warning,异常透传为 None(不抛)
    """
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
    """按文件名日期滚动清理(audit 30 天清理抽出)。

    解析文件名 "{prefix}YYYY-MM-DD.jsonl",超过 days 天的删除,返删除数。
    文件名解析失败 → 跳过 + log warning(不删,不抛)。

    Args:
        dir: 扫描目录(不存在 → 返 0,无 IO)。
        glob: 通配模式(如 "approvals-*.jsonl")。
        prefix: 文件名前缀(用于抽日期段,如 "approvals-" → 剩 "YYYY-MM-DD")。
        days: 保留天数(now - file_date < days 才删)。
        now: 测试注入时间点;None 用 datetime.now()。
        logger: 自定义 logger;None 用模块级 _log。
    """
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
