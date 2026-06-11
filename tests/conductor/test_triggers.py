"""FileTriggerWatcher 测试。

覆盖：
  - 首次 poll 不触发（无变化）
  - 文件 mtime 变化 → 触发 FileTriggerFact
  - 去抖：同文件在 debounce_secs 内只触发一次
  - 去抖窗口过后可再次触发
  - 不存在文件不报错
  - 注入假时钟（0 真实 sleep）
  - FileTriggerFact frozen 不变量
"""
from __future__ import annotations

import dataclasses
import time
from pathlib import Path

import pytest

from argos_agent.conductor.triggers import FileTriggerFact, FileTriggerWatcher


# ---------------------------------------------------------------------------
# FileTriggerFact frozen
# ---------------------------------------------------------------------------

class TestFileTriggerFact:
    def test_frozen(self):
        fact = FileTriggerFact(
            path="/tmp/foo.txt",
            mtime=1000.0,
            glob="*.txt",
            detected_at=1001.0,
        )
        with pytest.raises((AttributeError, TypeError, dataclasses.FrozenInstanceError)):
            fact.mtime = 9999.0  # type: ignore[misc]

    def test_slots(self):
        fact = FileTriggerFact(path="/a", mtime=1.0, glob="*", detected_at=2.0)
        assert "__slots__" in type(fact).__dict__

    def test_hashable(self):
        fact = FileTriggerFact(path="/a", mtime=1.0, glob="*", detected_at=2.0)
        s = {fact}
        assert fact in s


# ---------------------------------------------------------------------------
# FileTriggerWatcher 基本行为
# ---------------------------------------------------------------------------

class TestFileTriggerWatcherBasic:
    def test_no_trigger_on_first_poll_unchanged(self, tmp_path: Path):
        """首次 poll：文件存在但 mtime 无变化 → 触发（因为是新文件）。

        注意：首次 poll 时 _known_mtimes 为空，所有匹配文件都视为"新出现" → 产出 fact。
        """
        f = tmp_path / "req.txt"
        f.write_text("deps")

        t = [0.0]
        clock = lambda: t[0]

        w = FileTriggerWatcher(
            "req.txt",
            base_dir=tmp_path,
            debounce_secs=5.0,
            clock=clock,
        )
        # 首次 poll（t=0）
        facts = w.poll()
        assert len(facts) == 1
        assert facts[0].path == str(f.resolve())

    def test_no_retrigger_within_debounce(self, tmp_path: Path):
        """去抖：首次触发后，debounce 窗口内 mtime 再次变化不重复触发。"""
        f = tmp_path / "req.txt"
        f.write_text("deps")

        t = [0.0]
        clock = lambda: t[0]

        w = FileTriggerWatcher(
            "req.txt",
            base_dir=tmp_path,
            debounce_secs=5.0,
            clock=clock,
        )
        # 首次 poll → 产出 fact
        facts1 = w.poll()
        assert len(facts1) == 1

        # t=1（未超 debounce=5s），修改 mtime
        t[0] = 1.0
        f.write_text("deps updated")
        # 强制 mtime 变化（write_text 通常够用，但在极快文件系统上可能相同）
        import os
        os.utime(str(f), (t[0] + 10, t[0] + 10))

        facts2 = w.poll()
        # 在去抖窗口内 → 不触发
        assert len(facts2) == 0

    def test_retrigger_after_debounce_window(self, tmp_path: Path):
        """去抖窗口过后可再次触发。"""
        f = tmp_path / "req.txt"
        f.write_text("deps")

        t = [0.0]
        clock = lambda: t[0]

        w = FileTriggerWatcher(
            "req.txt",
            base_dir=tmp_path,
            debounce_secs=5.0,
            clock=clock,
        )
        # 首次触发
        facts1 = w.poll()
        assert len(facts1) == 1

        # 推进时钟超过 debounce，并更新 mtime
        t[0] = 10.0  # 10s > debounce=5s
        import os
        os.utime(str(f), (999.0, 999.0))  # 不同于初始 mtime

        facts2 = w.poll()
        assert len(facts2) == 1
        assert facts2[0].detected_at == 10.0

    def test_no_facts_when_no_files_match(self, tmp_path: Path):
        """没有匹配文件 → poll 返回空列表。"""
        t = [0.0]
        w = FileTriggerWatcher(
            "*.txt",
            base_dir=tmp_path,
            clock=lambda: t[0],
        )
        assert w.poll() == []

    def test_multiple_files_each_trigger(self, tmp_path: Path):
        """多个匹配文件，每个首次 poll 各产出一条 fact。"""
        (tmp_path / "a.txt").write_text("a")
        (tmp_path / "b.txt").write_text("b")

        t = [0.0]
        w = FileTriggerWatcher(
            "*.txt",
            base_dir=tmp_path,
            clock=lambda: t[0],
        )
        facts = w.poll()
        assert len(facts) == 2
        paths = {f.path for f in facts}
        assert any("a.txt" in p for p in paths)
        assert any("b.txt" in p for p in paths)

    def test_fact_fields_populated_correctly(self, tmp_path: Path):
        """FileTriggerFact 字段正确填充。"""
        f = tmp_path / "watch.txt"
        f.write_text("content")

        t = [42.0]
        w = FileTriggerWatcher(
            "watch.txt",
            base_dir=tmp_path,
            clock=lambda: t[0],
        )
        facts = w.poll()
        assert len(facts) == 1
        fact = facts[0]
        assert fact.glob == "watch.txt"
        assert fact.detected_at == 42.0
        assert fact.mtime > 0

    def test_clock_injected_not_real_time(self, tmp_path: Path):
        """验证 detected_at 来自注入时钟，不是真实时间。"""
        f = tmp_path / "x.txt"
        f.write_text("hi")

        fake_now = 999_999.0
        w = FileTriggerWatcher(
            "x.txt",
            base_dir=tmp_path,
            clock=lambda: fake_now,
        )
        facts = w.poll()
        assert len(facts) == 1
        assert facts[0].detected_at == fake_now


# ---------------------------------------------------------------------------
# 去抖精确测试
# ---------------------------------------------------------------------------

class TestDebounce:
    def test_debounce_boundary_exact(self, tmp_path: Path):
        """t = debounce_secs 时（等于，不超过）→ 不触发。"""
        f = tmp_path / "b.txt"
        f.write_text("v1")

        t = [0.0]
        clock = lambda: t[0]
        debounce = 5.0

        w = FileTriggerWatcher("b.txt", base_dir=tmp_path, debounce_secs=debounce, clock=clock)
        w.poll()  # 首次 t=0 触发

        t[0] = debounce  # 等于 debounce，不超过
        import os
        os.utime(str(f), (888.0, 888.0))
        facts = w.poll()
        assert len(facts) == 0

    def test_debounce_just_over(self, tmp_path: Path):
        """t = debounce_secs + epsilon → 触发。"""
        f = tmp_path / "c.txt"
        f.write_text("v1")

        t = [0.0]
        clock = lambda: t[0]
        debounce = 5.0

        w = FileTriggerWatcher("c.txt", base_dir=tmp_path, debounce_secs=debounce, clock=clock)
        w.poll()

        t[0] = debounce + 0.001
        import os
        os.utime(str(f), (777.0, 777.0))
        facts = w.poll()
        assert len(facts) == 1

    def test_same_file_multiple_polls_idempotent(self, tmp_path: Path):
        """文件 mtime 未变化，连续 poll 只在首次产出 fact（之后 mtime 缓存相同，不再进去）。"""
        f = tmp_path / "d.txt"
        f.write_text("v1")

        t = [0.0]
        clock = lambda: t[0]
        w = FileTriggerWatcher("d.txt", base_dir=tmp_path, debounce_secs=1.0, clock=clock)

        facts1 = w.poll()  # 首次：新文件触发
        assert len(facts1) == 1

        t[0] = 5.0  # 超过 debounce
        # mtime 未变 → _known_mtimes[path] 与当前 mtime 相同 → 不产出
        facts2 = w.poll()
        assert len(facts2) == 0


# ═══════════════════════════════════════════════════════
# 边界牢笼回归(终审 major):glob 带 .. 不得逃出 base_dir
# ═══════════════════════════════════════════════════════

class TestGlobBoundaryJail:
    def test_dotdot_glob_cannot_escape_base_dir(self, tmp_path):
        """pattern 含 .. 时,base_dir 之外的匹配必须被丢弃(fail-closed)。"""
        base = tmp_path / "ws"
        base.mkdir()
        secret = tmp_path / "secret.txt"   # base 之外
        secret.write_text("leak")
        inside = base / "ok.txt"
        inside.write_text("fine")

        from argos_agent.conductor.triggers import FileTriggerWatcher
        w = FileTriggerWatcher("../*.txt", base_dir=base, clock=lambda: 100.0)
        paths = w._match_glob()
        assert str(secret.resolve()) not in paths, f"越界泄漏: {paths}"
        for p in paths:
            assert str(base.resolve()) in p, f"返回了 base 外路径: {p}"

    def test_symlink_escape_also_jailed(self, tmp_path):
        """base 内符号链接指向外部文件 → resolve 后越界,同样丢弃。"""
        base = tmp_path / "ws"
        base.mkdir()
        outside = tmp_path / "outside.txt"
        outside.write_text("leak")
        (base / "link.txt").symlink_to(outside)

        from argos_agent.conductor.triggers import FileTriggerWatcher
        w = FileTriggerWatcher("*.txt", base_dir=base, clock=lambda: 100.0)
        paths = w._match_glob()
        assert str(outside.resolve()) not in paths, f"symlink 越界泄漏: {paths}"
