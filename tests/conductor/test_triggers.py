from __future__ import annotations

import dataclasses
import time
from pathlib import Path

import pytest

from argos.conductor.triggers import FileTriggerFact, FileTriggerWatcher


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
# ---------------------------------------------------------------------------

class TestFileTriggerWatcherBasic:
    def test_no_trigger_on_first_poll_unchanged(self, tmp_path: Path):
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
        facts = w.poll()
        assert len(facts) == 1
        assert facts[0].path == str(f.resolve())

    def test_no_retrigger_within_debounce(self, tmp_path: Path):
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
        facts1 = w.poll()
        assert len(facts1) == 1

        t[0] = 1.0
        f.write_text("deps updated")
        import os
        os.utime(str(f), (t[0] + 10, t[0] + 10))

        facts2 = w.poll()
        assert len(facts2) == 0

    def test_retrigger_after_debounce_window(self, tmp_path: Path):
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
        facts1 = w.poll()
        assert len(facts1) == 1

        t[0] = 10.0  # 10s > debounce=5s
        import os
        os.utime(str(f), (999.0, 999.0))

        facts2 = w.poll()
        assert len(facts2) == 1
        assert facts2[0].detected_at == 10.0

    def test_no_facts_when_no_files_match(self, tmp_path: Path):
        t = [0.0]
        w = FileTriggerWatcher(
            "*.txt",
            base_dir=tmp_path,
            clock=lambda: t[0],
        )
        assert w.poll() == []

    def test_multiple_files_each_trigger(self, tmp_path: Path):
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
# ---------------------------------------------------------------------------

class TestDebounce:
    def test_debounce_boundary_exact(self, tmp_path: Path):
        f = tmp_path / "b.txt"
        f.write_text("v1")

        t = [0.0]
        clock = lambda: t[0]
        debounce = 5.0

        w = FileTriggerWatcher("b.txt", base_dir=tmp_path, debounce_secs=debounce, clock=clock)
        w.poll()

        t[0] = debounce
        import os
        os.utime(str(f), (888.0, 888.0))
        facts = w.poll()
        assert len(facts) == 0

    def test_debounce_just_over(self, tmp_path: Path):
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
        f = tmp_path / "d.txt"
        f.write_text("v1")

        t = [0.0]
        clock = lambda: t[0]
        w = FileTriggerWatcher("d.txt", base_dir=tmp_path, debounce_secs=1.0, clock=clock)

        facts1 = w.poll()
        assert len(facts1) == 1

        t[0] = 5.0
        facts2 = w.poll()
        assert len(facts2) == 0


# ═══════════════════════════════════════════════════════
# ═══════════════════════════════════════════════════════

class TestGlobBoundaryJail:
    def test_dotdot_glob_cannot_escape_base_dir(self, tmp_path):
        base = tmp_path / "ws"
        base.mkdir()
        secret = tmp_path / "secret.txt"
        secret.write_text("leak")
        inside = base / "ok.txt"
        inside.write_text("fine")

        from argos.conductor.triggers import FileTriggerWatcher
        w = FileTriggerWatcher("../*.txt", base_dir=base, clock=lambda: 100.0)
        paths = w._match_glob()
        assert str(secret.resolve()) not in paths, f"越界泄漏: {paths}"
        for p in paths:
            assert str(base.resolve()) in p, f"返回了 base 外路径: {p}"

    def test_symlink_escape_also_jailed(self, tmp_path):
        base = tmp_path / "ws"
        base.mkdir()
        outside = tmp_path / "outside.txt"
        outside.write_text("leak")
        (base / "link.txt").symlink_to(outside)

        from argos.conductor.triggers import FileTriggerWatcher
        w = FileTriggerWatcher("*.txt", base_dir=base, clock=lambda: 100.0)
        paths = w._match_glob()
        assert str(outside.resolve()) not in paths, f"symlink 越界泄漏: {paths}"
