"""cronlite — 零依赖 cron-lite 时间表达式解析器（设计 §9 自治面）。

支持格式：
  @hourly                    每整点（等价 "0 * * * *"）
  @daily / @midnight         每天 00:00（等价 "0 0 * * *"）
  @weekly                    每周日 00:00（等价 "0 0 * * 0"）
  "HH:MM"                    每日定点（如 "09:00"、"23:30"）
  "every <N>(s|m|h)"         固定间隔（如 "every 30m"、"every 2h"、"every 10s"）
  五段标准 cron 子集          "分 时 日 月 周"，每段支持：
                               * 匹配全部
                               整数
                               */N 步进（N≥1）

不支持：逗号列表、连字符范围、L/W/#/? 等扩展语法。
非法 spec → 立即抛 ValueError（fail-loud，不静默降级）。

接口：
  next_due(spec: str, now: float, *, clock: Callable[[], float] | None = None) -> float
    返回 now 之后下一次触发的 Unix 时间戳（单位秒，精度到分钟）。
    注入 clock 供测试替换时钟（禁止直接调用 time.time()）。
"""
from __future__ import annotations

import re
import time as _time_module
from datetime import datetime, timezone
from typing import Callable

from argos.i18n import t

# -----------------------------------------------------------------------
# 常量 / 别名
# -----------------------------------------------------------------------

_ALIASES: dict[str, str] = {
    "@hourly":   "0 * * * *",
    "@daily":    "0 0 * * *",
    "@midnight": "0 0 * * *",
    "@weekly":   "0 0 * * 0",
}

# "HH:MM" — 每天定点
_HHMM_RE = re.compile(r"^(\d{1,2}):(\d{2})$")

# "every <N>(s|m|h)" — 固定间隔
_EVERY_RE = re.compile(r"^every\s+(\d+)\s*(s|m|h)$", re.IGNORECASE)

# 五段 cron 字段（每段：* | 整数 | */N）
_FIELD_RE = re.compile(r"^\*(?:/(\d+))?$|^(\d+)$")


# -----------------------------------------------------------------------
# 五段 cron 内部辅助
# -----------------------------------------------------------------------

def _parse_field(token: str, lo: int, hi: int, label: str) -> set[int]:
    """解析单个 cron 字段（lo..hi 闭区间），返回匹配的整数集合。

    支持：
      *        → range(lo, hi+1)
      */N      → range(lo, hi+1, N)
      整数 N   → {N}（超界抛 ValueError）
    """
    m = _FIELD_RE.match(token)
    if not m:
        raise ValueError(t("cond.cronlite.field_invalid", label=label, token=token))

    step_str, num_str = m.group(1), m.group(2)

    if num_str is not None:
        # 纯整数
        n = int(num_str)
        if not (lo <= n <= hi):
            raise ValueError(
                t("cond.cronlite.field_out_of_range", label=label, n=n, lo=lo, hi=hi)
            )
        return {n}
    else:
        # * 或 */N
        step = int(step_str) if step_str is not None else 1
        if step < 1:
            raise ValueError(
                t("cond.cronlite.field_step_lt1", label=label, step=step)
            )
        return set(range(lo, hi + 1, step))


def _parse_five_field(spec: str) -> tuple[set[int], set[int], set[int], set[int], set[int]]:
    """解析五段 cron spec，返回 (minutes, hours, mdays, months, wdays)。"""
    parts = spec.split()
    if len(parts) != 5:
        raise ValueError(
            t("cond.cronlite.five_field_count", count=len(parts), spec=spec)
        )
    minute_tok, hour_tok, mday_tok, month_tok, wday_tok = parts
    minutes = _parse_field(minute_tok, 0, 59, t("cond.field_minute"))
    hours   = _parse_field(hour_tok,   0, 23, t("cond.field_hour"))
    mdays   = _parse_field(mday_tok,   1, 31, t("cond.field_mday"))
    months  = _parse_field(month_tok,  1, 12, t("cond.field_month"))
    wdays   = _parse_field(wday_tok,   0,  6, t("cond.field_wday"))
    return minutes, hours, mdays, months, wdays


# -----------------------------------------------------------------------
# weekday 映射（Python datetime.weekday() 0=Mon，cron 0=Sun）
# -----------------------------------------------------------------------

def _python_wday_to_cron(wday: int) -> int:
    """Python datetime.weekday()（0=Mon…6=Sun）→ cron 惯例（0=Sun…6=Sat）。"""
    return (wday + 1) % 7


def _next_cron_v2(
    minutes: set[int],
    hours:   set[int],
    mdays:   set[int],
    months:  set[int],
    wdays:   set[int],
    now_ts:  float,
) -> float:
    """修正版：正确映射 Python weekday → cron wday（0=Sun）。"""
    MAX_MINS = 366 * 24 * 60
    next_sec = (int(now_ts) // 60 + 1) * 60

    for _ in range(MAX_MINS):
        dt_c = datetime.fromtimestamp(next_sec, tz=timezone.utc)
        cron_wday = _python_wday_to_cron(dt_c.weekday())
        if (
            dt_c.month   in months
            and dt_c.day in mdays
            and cron_wday in wdays
            and dt_c.hour in hours
            and dt_c.minute in minutes
        ):
            return float(next_sec)
        next_sec += 60

    raise ValueError(t("cond.cronlite.no_trigger_in_year"))


# -----------------------------------------------------------------------
# 公开接口
# -----------------------------------------------------------------------

def next_due(
    spec: str,
    now: float,
    *,
    clock: Callable[[], float] | None = None,
) -> float:
    """计算 spec 在 now 之后的下一次触发 Unix 时间戳。

    参数：
        spec    cron-lite 表达式字符串
        now     参考时间点（Unix float，通常为当前时间）
        clock   仅签名一致性占位（engine/triggers 统一注入时钟的接口形状）;
                本纯函数只对 now 求值,不消费 clock。

    返回：下一次触发的 Unix 时间戳（float，精度到秒，实际精度到分钟）。

    异常：
        ValueError — spec 非法（fail-loud，不静默降级）。
        注意:跨闰年的稀疏 spec(如 '0 0 29 2 *' 从非闰年出发)下一触发点
        可能超出 366 天搜索窗而抛 ValueError —— fail-loud 不静默,属已知边界。
    """
    spec = spec.strip()

    # 1. 别名展开
    if spec in _ALIASES:
        spec = _ALIASES[spec]

    # 2. "HH:MM" — 每日定点
    m_hhmm = _HHMM_RE.match(spec)
    if m_hhmm:
        hh, mm = int(m_hhmm.group(1)), int(m_hhmm.group(2))
        if not (0 <= hh <= 23 and 0 <= mm <= 59):
            raise ValueError(t("cond.cronlite.hhmm_out_of_range", spec=spec))
        # 转为等价 cron：mm hh * * *
        minutes = {mm}
        hours   = {hh}
        mdays   = set(range(1, 32))
        months  = set(range(1, 13))
        wdays   = set(range(0, 7))
        return _next_cron_v2(minutes, hours, mdays, months, wdays, now)

    # 3. "every <N>(s|m|h)" — 固定间隔
    m_every = _EVERY_RE.match(spec)
    if m_every:
        n = int(m_every.group(1))
        unit = m_every.group(2).lower()
        if n < 1:
            raise ValueError(t("cond.cronlite.every_n_lt1", n=n))
        multiplier = {"s": 1, "m": 60, "h": 3600}[unit]
        interval = n * multiplier
        # 下一次 = now + interval（对齐到 interval 边界，向上取）
        next_ts = (int(now) // interval + 1) * interval
        return float(next_ts)

    # 4. 五段 cron
    minutes, hours, mdays, months, wdays = _parse_five_field(spec)
    return _next_cron_v2(minutes, hours, mdays, months, wdays, now)
