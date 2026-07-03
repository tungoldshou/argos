from __future__ import annotations

import asyncio
import json
import time

import pytest

from argos.hooks.config import HookHandler, HookMatcherEntry, HooksConfig
from argos.hooks.matcher import match
from argos.hooks.payload import build_pre_payload
from argos.hooks import runner as _runner
from argos.hooks.runner import fire, HookFireResult


@pytest.fixture(autouse=True)
def _isolated_singleton(monkeypatch):
    from argos.hooks import _reset_config
    _reset_config()
    yield
    _reset_config()


def _set_config(*entries_for_pre):
    cfg = HooksConfig(entries={"PreToolUse": list(entries_for_pre)})
    from argos.hooks import _config
    import argos.hooks as h
    h._config = cfg
    return cfg


@pytest.mark.asyncio
async def test_fire_exit_zero_success():
    """command='echo ok' exit 0 → success=True。"""
    h = HookHandler(type="command", command="echo ok", timeout=5000)
    _set_config(HookMatcherEntry(matcher="*", hooks=(h,)))
    payload = build_pre_payload(
        session_id="s", cwd="/tmp", code="write_file('a','1')", tool_names=["write_file"],
    )
    r = await fire("PreToolUse", payload, cwd="/tmp", session_id="s")
    assert isinstance(r, HookFireResult)
    assert r.success is True
    assert r.returncode == 0
    assert "ok" in r.stdout


@pytest.mark.asyncio
async def test_fire_exit_nonzero_fail():
    """command='false' exit 1 → success=False, returncode=1。"""
    h = HookHandler(type="command", command="false", timeout=5000)
    _set_config(HookMatcherEntry(matcher="*", hooks=(h,)))
    payload = build_pre_payload(session_id="s", cwd="/tmp", code="x", tool_names=[])
    r = await fire("PreToolUse", payload, cwd="/tmp", session_id="s")
    assert r.success is False
    assert r.returncode == 1


@pytest.mark.asyncio
async def test_fire_timeout_kills_process():
    h = HookHandler(type="command", command="sleep 5", timeout=200)
    _set_config(HookMatcherEntry(matcher="*", hooks=(h,)))
    payload = build_pre_payload(session_id="s", cwd="/tmp", code="x", tool_names=[])
    t0 = time.time()
    r = await fire("PreToolUse", payload, cwd="/tmp", session_id="s")
    elapsed = time.time() - t0
    assert elapsed < 3.0
    assert r.success is False
    assert r.timed_out is True


@pytest.mark.asyncio
async def test_fire_passes_stdin_json():
    h = HookHandler(type="command", command="cat", timeout=5000)
    _set_config(HookMatcherEntry(matcher="*", hooks=(h,)))
    payload = build_pre_payload(
        session_id="s", cwd="/tmp", code="x", tool_names=["write_file"],
    )
    expected = json.dumps(payload, ensure_ascii=False)
    r = await fire("PreToolUse", payload, cwd="/tmp", session_id="s")
    assert r.stdout.strip() == expected


@pytest.mark.asyncio
async def test_fire_parallel_3_hooks_faster_than_serial():
    h1 = HookHandler(type="command", command="sleep 0.5 && echo a", timeout=10000)
    h2 = HookHandler(type="command", command="sleep 0.5 && echo b", timeout=10000)
    h3 = HookHandler(type="command", command="sleep 0.5 && echo c", timeout=10000)
    _set_config(HookMatcherEntry(matcher="*", hooks=(h1, h2, h3)))
    payload = build_pre_payload(session_id="s", cwd="/tmp", code="x", tool_names=[])
    t0 = time.time()
    r = await fire("PreToolUse", payload, cwd="/tmp", session_id="s")
    elapsed = time.time() - t0
    assert elapsed < 1.4
    assert len(r.per_hook) == 3


@pytest.mark.asyncio
async def test_fire_stdout_invalid_json_ignored():
    h = HookHandler(type="command", command="echo 'not json'", timeout=5000)
    _set_config(HookMatcherEntry(matcher="*", hooks=(h,)))
    payload = build_pre_payload(session_id="s", cwd="/tmp", code="x", tool_names=[])
    r = await fire("PreToolUse", payload, cwd="/tmp", session_id="s")
    assert r.success is True
    assert r.stop_reason is None


@pytest.mark.asyncio
async def test_fire_stdout_json_stop_reason():
    h = HookHandler(
        type="command", command="printf %s '{\"stopReason\":\"blocked by audit\"}'",
        timeout=5000,
    )
    _set_config(HookMatcherEntry(matcher="*", hooks=(h,)))
    payload = build_pre_payload(session_id="s", cwd="/tmp", code="x", tool_names=[])
    r = await fire("PreToolUse", payload, cwd="/tmp", session_id="s")
    assert r.stop_reason == "blocked by audit"


@pytest.mark.asyncio
async def test_fire_command_not_found():
    h = HookHandler(
        type="command", command="nonexistent-bin-xyz-12345", timeout=5000,
    )
    _set_config(HookMatcherEntry(matcher="*", hooks=(h,)))
    payload = build_pre_payload(session_id="s", cwd="/tmp", code="x", tool_names=[])
    r = await fire("PreToolUse", payload, cwd="/tmp", session_id="s")
    assert r.not_found is True
    assert r.success is False


@pytest.mark.asyncio
async def test_fire_env_argos_hook_event_injected():
    h = HookHandler(
        type="command", command="bash -c 'echo $ARGOS_HOOK_EVENT'", timeout=5000,
    )
    _set_config(HookMatcherEntry(matcher="*", hooks=(h,)))
    payload = build_pre_payload(session_id="s", cwd="/tmp", code="x", tool_names=[])
    r = await fire("PreToolUse", payload, cwd="/tmp", session_id="s")
    assert "PreToolUse" in r.stdout


@pytest.mark.asyncio
async def test_fire_template_replacement_cwd(tmp_path):
    h = HookHandler(
        type="command", command="echo cwd={cwd} tools={tool_names}",
        timeout=5000,
    )
    _set_config(HookMatcherEntry(matcher="*", hooks=(h,)))
    payload = build_pre_payload(
        session_id="s", cwd=str(tmp_path), code="x", tool_names=["write_file", "run_command"],
    )
    r = await fire("PreToolUse", payload, cwd=str(tmp_path), session_id="s")
    assert f"cwd={tmp_path}" in r.stdout
    assert "write_file,run_command" in r.stdout


@pytest.mark.asyncio
async def test_fire_event_with_no_handlers_noop():
    payload = build_pre_payload(session_id="s", cwd="/tmp", code="x", tool_names=[])
    r = await fire("PostToolUse", payload, cwd="/tmp", session_id="s")
    assert r.success is True
    assert list(r.per_hook) == []
    assert r.not_found is False


@pytest.mark.asyncio
async def test_fire_pre_blocking_sets_success_false_for_any_nonzero():
    h_ok = HookHandler(type="command", command="true", timeout=5000)
    h_fail = HookHandler(type="command", command="false", timeout=5000)
    _set_config(HookMatcherEntry(matcher="*", hooks=(h_ok, h_fail)))
    payload = build_pre_payload(session_id="s", cwd="/tmp", code="x", tool_names=[])
    r = await fire("PreToolUse", payload, cwd="/tmp", session_id="s")
    assert r.success is False
