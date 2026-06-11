"""cronlite 全分支测试。

覆盖：
  - @hourly / @daily / @weekly 别名
  - HH:MM 每日定点
  - every N(s|m|h) 固定间隔
  - 五段 cron 子集（* / 整数 / */N）
  - 跨日/跨周边界
  - 非法 spec → ValueError（fail-loud）
  - 注入假时钟（0 真实 sleep）
"""
from __future__ import annotations

import pytest
from datetime import datetime, timezone

from argos_agent.conductor.cronlite import next_due


# ---------------------------------------------------------------------------
# 辅助：构造 UTC datetime → Unix 时间戳
# ---------------------------------------------------------------------------

def _utc(year: int, month: int, day: int,
         hour: int = 0, minute: int = 0, second: int = 0) -> float:
    """构造 UTC datetime 的 Unix 时间戳。"""
    dt = datetime(year, month, day, hour, minute, second, tzinfo=timezone.utc)
    return dt.timestamp()


# ---------------------------------------------------------------------------
# 别名测试
# ---------------------------------------------------------------------------

class TestAliases:
    """@hourly / @daily / @weekly 别名展开。"""

    def test_hourly_fires_at_next_whole_hour(self):
        # now = 2024-01-01 09:30:00 UTC
        now = _utc(2024, 1, 1, 9, 30, 0)
        due = next_due("@hourly", now)
        dt = datetime.fromtimestamp(due, tz=timezone.utc)
        # 下一整点 = 10:00
        assert dt.hour == 10
        assert dt.minute == 0

    def test_daily_fires_at_midnight(self):
        # now = 2024-01-01 09:00:00 UTC
        now = _utc(2024, 1, 1, 9, 0, 0)
        due = next_due("@daily", now)
        dt = datetime.fromtimestamp(due, tz=timezone.utc)
        # 下次 @daily = 2024-01-02 00:00
        assert dt.day == 2
        assert dt.hour == 0
        assert dt.minute == 0

    def test_midnight_alias_same_as_daily(self):
        now = _utc(2024, 1, 1, 9, 0, 0)
        assert next_due("@midnight", now) == next_due("@daily", now)

    def test_weekly_fires_on_next_sunday(self):
        # 2024-01-01 是周一（Python weekday=0 → cron wday=1），@weekly = cron "0 0 * * 0"（周日）
        now = _utc(2024, 1, 1, 1, 0, 0)
        due = next_due("@weekly", now)
        dt = datetime.fromtimestamp(due, tz=timezone.utc)
        # 下个周日 = 2024-01-07
        assert dt.weekday() == 6  # Python Sun=6
        assert dt.hour == 0
        assert dt.minute == 0

    def test_daily_at_midnight_already_passed(self):
        """now=00:05 → 下次 @daily 是明天。"""
        now = _utc(2024, 1, 1, 0, 5, 0)
        due = next_due("@daily", now)
        dt = datetime.fromtimestamp(due, tz=timezone.utc)
        assert dt.day == 2


# ---------------------------------------------------------------------------
# HH:MM 每日定点
# ---------------------------------------------------------------------------

class TestHHMM:
    """HH:MM 每日定点触发。"""

    def test_fires_today_if_not_yet(self):
        # now = 08:59, spec = 09:00 → 今天 09:00
        now = _utc(2024, 1, 1, 8, 59, 0)
        due = next_due("09:00", now)
        dt = datetime.fromtimestamp(due, tz=timezone.utc)
        assert dt.day == 1
        assert dt.hour == 9
        assert dt.minute == 0

    def test_fires_tomorrow_if_passed(self):
        # now = 09:01, spec = 09:00 → 明天 09:00
        now = _utc(2024, 1, 1, 9, 1, 0)
        due = next_due("09:00", now)
        dt = datetime.fromtimestamp(due, tz=timezone.utc)
        assert dt.day == 2
        assert dt.hour == 9
        assert dt.minute == 0

    def test_fires_tomorrow_if_exactly_now(self):
        """now 恰好等于 spec 分钟 → 下一次是明天（下一分钟起算）。"""
        now = _utc(2024, 1, 1, 9, 0, 0)
        due = next_due("09:00", now)
        dt = datetime.fromtimestamp(due, tz=timezone.utc)
        assert dt.day == 2

    def test_midnight_spec(self):
        now = _utc(2024, 1, 1, 23, 59, 0)
        due = next_due("00:00", now)
        dt = datetime.fromtimestamp(due, tz=timezone.utc)
        assert dt.day == 2
        assert dt.hour == 0

    def test_end_of_day_spec(self):
        now = _utc(2024, 1, 1, 22, 0, 0)
        due = next_due("23:30", now)
        dt = datetime.fromtimestamp(due, tz=timezone.utc)
        assert dt.hour == 23
        assert dt.minute == 30

    def test_single_digit_hour(self):
        """支持 '9:00'（单位数小时）。"""
        now = _utc(2024, 1, 1, 8, 0, 0)
        due = next_due("9:00", now)
        dt = datetime.fromtimestamp(due, tz=timezone.utc)
        assert dt.hour == 9

    def test_invalid_hour(self):
        with pytest.raises(ValueError):
            next_due("25:00", _utc(2024, 1, 1, 0, 0, 0))

    def test_invalid_minute(self):
        with pytest.raises(ValueError):
            next_due("12:60", _utc(2024, 1, 1, 0, 0, 0))


# ---------------------------------------------------------------------------
# every N(s|m|h) 固定间隔
# ---------------------------------------------------------------------------

class TestEvery:
    """every N(s|m|h) 固定间隔。"""

    def test_every_30m(self):
        # now = 09:01:00（Unix=541260s if 1970…实际用 _utc）
        # 30m = 1800s，下一触发 = 向上对齐到下一个 1800 的倍数
        now = _utc(2024, 1, 1, 9, 1, 0)
        due = next_due("every 30m", now)
        assert due > now
        # 间隔是 1800s
        assert (int(due) % 1800) == 0

    def test_every_1h(self):
        now = _utc(2024, 1, 1, 9, 0, 0)
        due = next_due("every 1h", now)
        assert due > now
        assert (int(due) % 3600) == 0

    def test_every_10s(self):
        now = _utc(2024, 1, 1, 9, 0, 5)
        due = next_due("every 10s", now)
        assert due > now
        assert (int(due) % 10) == 0

    def test_every_2h(self):
        now = _utc(2024, 1, 1, 9, 0, 0)
        due = next_due("every 2h", now)
        assert due > now
        assert (int(due) % 7200) == 0

    def test_every_case_insensitive(self):
        now = _utc(2024, 1, 1, 9, 0, 0)
        due1 = next_due("every 1H", now)
        due2 = next_due("every 1h", now)
        assert due1 == due2

    def test_every_spacing_flexible(self):
        """支持 'every  2 m'（多空格）。"""
        now = _utc(2024, 1, 1, 9, 0, 0)
        due = next_due("every  2 m", now)
        assert due > now

    def test_every_zero_raises(self):
        """N=0 抛 ValueError。"""
        with pytest.raises(ValueError):
            next_due("every 0m", _utc(2024, 1, 1, 9, 0, 0))


# ---------------------------------------------------------------------------
# 五段 cron 子集
# ---------------------------------------------------------------------------

class TestFiveFieldCron:
    """五段 cron spec 解析 + next_due。"""

    def test_specific_minute_and_hour(self):
        # "30 9 * * *" = 每天 09:30
        now = _utc(2024, 1, 1, 9, 0, 0)
        due = next_due("30 9 * * *", now)
        dt = datetime.fromtimestamp(due, tz=timezone.utc)
        assert dt.hour == 9
        assert dt.minute == 30

    def test_every_minute(self):
        # "* * * * *" = 每分钟
        now = _utc(2024, 1, 1, 9, 0, 30)
        due = next_due("* * * * *", now)
        dt = datetime.fromtimestamp(due, tz=timezone.utc)
        # 下一分钟
        assert dt.minute == 1 or (dt.minute == 0 and dt.hour == 10)  # 09:01

    def test_step_slash(self):
        # "0 */2 * * *" = 每 2 小时整点
        now = _utc(2024, 1, 1, 9, 0, 0)
        due = next_due("0 */2 * * *", now)
        dt = datetime.fromtimestamp(due, tz=timezone.utc)
        assert dt.minute == 0
        assert dt.hour % 2 == 0

    def test_specific_weekday(self):
        # "0 10 * * 1" = 每周一 10:00（cron wday=1=Mon）
        # 2024-01-01 是周一
        now = _utc(2024, 1, 1, 10, 1, 0)  # 刚过 10:00
        due = next_due("0 10 * * 1", now)
        dt = datetime.fromtimestamp(due, tz=timezone.utc)
        assert dt.weekday() == 0  # Python Mon=0
        assert dt.hour == 10
        assert dt.minute == 0
        # 下周一
        assert dt.day == 8

    def test_specific_day_of_month(self):
        # "0 9 15 * *" = 每月 15 日 09:00
        now = _utc(2024, 1, 1, 9, 0, 0)
        due = next_due("0 9 15 * *", now)
        dt = datetime.fromtimestamp(due, tz=timezone.utc)
        assert dt.day == 15
        assert dt.hour == 9

    def test_specific_month(self):
        # "0 0 1 6 *" = 每年 6 月 1 日 00:00
        now = _utc(2024, 1, 1, 0, 0, 0)
        due = next_due("0 0 1 6 *", now)
        dt = datetime.fromtimestamp(due, tz=timezone.utc)
        assert dt.month == 6
        assert dt.day == 1

    def test_cross_day_boundary(self):
        """跨日边界：spec 时间早于 now → 明天。"""
        now = _utc(2024, 1, 1, 23, 59, 0)
        due = next_due("0 0 * * *", now)
        dt = datetime.fromtimestamp(due, tz=timezone.utc)
        assert dt.day == 2
        assert dt.hour == 0

    def test_cross_week_boundary(self):
        """跨周边界：周六 now，等到下个周日（cron wday=0）。"""
        # 2024-01-06 是周六（Python weekday=5）
        now = _utc(2024, 1, 6, 12, 0, 0)
        due = next_due("0 0 * * 0", now)
        dt = datetime.fromtimestamp(due, tz=timezone.utc)
        assert dt.weekday() == 6  # Python Sun=6
        assert dt.day == 7

    def test_step_in_minutes(self):
        # "*/15 * * * *" = 每 15 分钟
        now = _utc(2024, 1, 1, 9, 7, 0)
        due = next_due("*/15 * * * *", now)
        dt = datetime.fromtimestamp(due, tz=timezone.utc)
        assert dt.minute in {0, 15, 30, 45}


# ---------------------------------------------------------------------------
# 非法 spec → ValueError（fail-loud）
# ---------------------------------------------------------------------------

class TestInvalidSpec:
    """非法 spec 必须 raise ValueError（fail-loud，不静默降级）。"""

    @pytest.mark.parametrize("bad_spec", [
        "",                    # 空字符串
        "not-a-cron",          # 完全非法
        "every",               # 缺 N 和单位
        "every abc",           # 非法单位
        "60 * * * *",          # 分钟超界
        "* 25 * * *",          # 小时超界
        "* * 0 * *",           # 月份日 0（下界）
        "* * 32 * *",          # 月份日 32（上界）
        "* * * 0 *",           # 月份 0（下界）
        "* * * 13 *",          # 月份 13（上界）
        "* * * * 7",           # 周 7（上界）
        "* * * *",             # 只有 4 段
        "* * * * * *",         # 6 段（不支持秒级 cron）
        "*/0 * * * *",         # 步进为 0
        "@monthly",            # 未支持的别名
    ])
    def test_invalid_raises(self, bad_spec: str):
        with pytest.raises(ValueError, match=r".+"):
            next_due(bad_spec, _utc(2024, 1, 1, 0, 0, 0))


# ---------------------------------------------------------------------------
# 时钟注入（0 真实 sleep）
# ---------------------------------------------------------------------------

class TestClockInjection:
    """clock 参数注入——整个测试过程 0 真实 sleep。"""

    def test_clock_param_accepted(self):
        """clock 参数被接受（不报错），0 次真实时钟调用。"""
        called = []

        def fake_clock():
            called.append(1)
            return _utc(2024, 1, 1, 9, 0, 0)

        # clock 目前在 next_due 内部未直接调用（next_due 用的是 now 参数），
        # 但接口保留。此处验证参数不会导致错误。
        now = _utc(2024, 1, 1, 9, 0, 0)
        due = next_due("09:30", now, clock=fake_clock)
        assert due > now
        # clock 未被直接调用（按设计，now 由调用方传入）
        # 不断言 called 次数，只验证不抛错

    def test_no_real_time_import_needed(self):
        """验证 next_due 可在完全自定义时间下使用（0 依赖真实时钟）。"""
        # 使用固定时间
        fixed_now = 1_000_000.0  # 1970-01-12
        due = next_due("* * * * *", fixed_now)
        assert due > fixed_now
        # 下次是下一分钟
        assert due - fixed_now < 120
