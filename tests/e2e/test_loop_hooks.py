from __future__ import annotations

import asyncio
import json
import os
import textwrap
import pytest

from argos.hooks import (
    _reset_config, get_config, fire,
)
from argos.hooks.config import HookHandler, HookMatcherEntry, HooksConfig
from argos.hooks.payload import (
    build_post_payload, build_pre_payload, build_session_start_payload,
    build_stop_payload, build_user_prompt_payload,
)
from argos.hooks.events import HookFired


def _set_hooks(entries_per_event: dict[str, list[HookMatcherEntry]]) -> None:
    import argos.hooks as h
    h._config = HooksConfig(entries=entries_per_event)


@pytest.fixture(autouse=True)
def _isolated(monkeypatch):
    import tempfile
    tmp = tempfile.mkdtemp()
    monkeypatch.setenv("HOME", tmp)
    _reset_config()
    yield
    _reset_config()


@pytest.mark.asyncio
async def test_pre_blocking_skips_exec_code(tmp_path):
    h_block2 = HookHandler(
        type="command",
        command="bash -c 'printf %s \"{\\\"stopReason\\\":\\\"blocked\\\"}\"; exit 2'",
        timeout=5000,
    )
    _set_hooks({"PreToolUse": [HookMatcherEntry(matcher="*", hooks=(h_block2,))]})
    payload = {
        "hook_event_name": "PreToolUse",
        "session_id": "s", "cwd": str(tmp_path), "code": "write_file('a','1')",
        "tool_names": ["write_file"],
    }
    r = await fire("PreToolUse", payload, cwd=str(tmp_path), session_id="s")
    assert r.success is False
    assert r.stop_reason == "blocked"


@pytest.mark.asyncio
async def test_pre_blocking_message_template():
    h = HookHandler(
        type="command",
        command="bash -c 'printf %s \"{\\\"stopReason\\\":\\\"secret detected\\\"}\"; exit 2'",
        timeout=5000,
    )
    _set_hooks({"PreToolUse": [HookMatcherEntry(matcher="*", hooks=(h,))]})
    payload = build_pre_payload(
        session_id="s", cwd="/tmp", code="write_file('a','1')", tool_names=["write_file"],
    )
    r = await fire("PreToolUse", payload, cwd="/tmp", session_id="s")
    assert r.stop_reason == "secret detected"


@pytest.mark.asyncio
async def test_post_hook_fires_after_sandbox_exec(tmp_path):
    target = tmp_path / "post_payload.json"
    h = HookHandler(
        type="command",
        command=f"bash -c 'cat > {target}'",
        timeout=5000,
    )
    _set_hooks({"PostToolUse": [HookMatcherEntry(matcher="*", hooks=(h,))]})
    payload = build_post_payload(
        session_id="s", cwd=str(tmp_path),
        code="write_file('a','1')", tool_names=["write_file"],
        stdout="hello", value_repr="[]", exc="", ok=True,
    )
    r = await fire("PostToolUse", payload, cwd=str(tmp_path), session_id="s")
    assert r.success is True
    assert target.exists()
    on_disk = json.loads(target.read_text())
    assert on_disk["stdout"] == "hello"
    assert on_disk["ok"] is True


@pytest.mark.asyncio
async def test_stop_hook_fires_with_verdict_status(tmp_path):
    target = tmp_path / "seen.json"
    h = HookHandler(
        type="command",
        command=f"bash -c 'cat > {target}'",
        timeout=5000,
    )
    _set_hooks({"Stop": [HookMatcherEntry(matcher=None, hooks=(h,))]})
    payload = build_stop_payload(
        session_id="s", cwd=str(tmp_path), goal="do x",
        verdict_status="passed", actions=3, elapsed_s=12.4, escalated=False,
    )
    r = await fire("Stop", payload, cwd=str(tmp_path), session_id="s")
    assert r.success is True
    seen = json.loads(target.read_text())
    assert seen["verdict_status"] == "passed"
    assert seen["actions"] == 3
    assert abs(seen["elapsed_s"] - 12.4) < 0.1


@pytest.mark.asyncio
async def test_user_prompt_submit_hook_fires_with_goal(tmp_path):
    target = tmp_path / "ups.json"
    h = HookHandler(
        type="command",
        command=f"bash -c 'cat > {target}'",
        timeout=5000,
    )
    _set_hooks({"UserPromptSubmit": [HookMatcherEntry(matcher=None, hooks=(h,))]})
    payload = build_user_prompt_payload(session_id="s", cwd=str(tmp_path), goal="fix bug")
    r = await fire("UserPromptSubmit", payload, cwd=str(tmp_path), session_id="s")
    assert r.success is True
    on_disk = json.loads(target.read_text())
    assert on_disk["goal"] == "fix bug"


@pytest.mark.asyncio
async def test_session_start_hook_fires_with_model_tier(tmp_path):
    target = tmp_path / "ss.json"
    h = HookHandler(
        type="command",
        command=f"bash -c 'cat > {target}'",
        timeout=5000,
    )
    _set_hooks({"SessionStart": [HookMatcherEntry(matcher=None, hooks=(h,))]})
    payload = build_session_start_payload(
        session_id="s", cwd=str(tmp_path), model_tier="default",
    )
    r = await fire("SessionStart", payload, cwd=str(tmp_path), session_id="s")
    assert r.success is True
    on_disk = json.loads(target.read_text())
    assert on_disk["model_tier"] == "default"


@pytest.mark.asyncio
async def test_pre_timeout_not_blocking():
    h = HookHandler(type="command", command="sleep 5", timeout=100)
    _set_hooks({"PreToolUse": [HookMatcherEntry(matcher="*", hooks=(h,))]})
    payload = build_pre_payload(
        session_id="s", cwd="/tmp", code="x", tool_names=[],
    )
    r = await fire("PreToolUse", payload, cwd="/tmp", session_id="s")
    assert r.timed_out is True
    assert r.success is False



@pytest.mark.asyncio
async def test_drive_emits_session_start_hook_fired(build_real_loop, tmp_path):
    from argos.hooks.events import HookFired as _HookFired

    marker = tmp_path / "hook_fired.marker"
    cmd = f"bash -c 'echo $ARGOS_HOOK_EVENT >> {marker}'"
    _set_hooks({
        "SessionStart": [HookMatcherEntry(matcher=None, hooks=(
            HookHandler(type="command", command=cmd, timeout=5000),
        ))],
    })

    scripts = [
        "```python\nwrite_file('a.py', '1')\n```\n完成了。",
    ]
    loop = build_real_loop(scripts)

    async for ev in loop.run(goal="echo hi", session_id="hooks-e2e-001"):
        pass

    assert marker.exists(), f"hook 至少应 fire 一次;marker={marker}"
    content = marker.read_text()
    assert "SessionStart" in content


@pytest.mark.asyncio
async def test_drive_pre_timeout_blocks_tool_execution(build_real_loop, tmp_path):
    h = HookHandler(type="command", command="sleep 5", timeout=100)
    _set_hooks({"PreToolUse": [HookMatcherEntry(matcher="*", hooks=(h,))]})

    scripts = [
        "```python\nwrite_file('blocked.py', '1')\n```\n",
        "完成了。",
    ]
    loop = build_real_loop(scripts, verify_cmd=None)

    async for _ev in loop.run(goal="write blocked file", session_id="hooks-timeout-001"):
        pass

    assert not (loop._workspace / "blocked.py").exists()


@pytest.mark.asyncio
async def test_drive_pre_blocking_yields_fail_hookfired(build_real_loop):
    from argos.hooks.events import HookFired as _HookFired

    reject_cmd = "bash -c 'printf %s \"{\\\"stopReason\\\":\\\"audit blocked\\\"}\"; exit 2'"
    _set_hooks({
        "PreToolUse": [HookMatcherEntry(matcher="*", hooks=(
            HookHandler(type="command", command=reject_cmd, timeout=5000),
        ))],
    })

    saw_pre_reject = False
    scripts = [
        "```python\nwrite_file('a.py', '1')\n```\n",
        "```python\nwrite_file('a.py', '1')\n```\n",
        "完成了。",
    ]
    loop = build_real_loop(scripts, verify_cmd=None)
    async for ev in loop.run(goal="echo hi", session_id="hooks-block-001"):
        if isinstance(ev, _HookFired):
            if ev.event_name == "PreToolUse" and not ev.success:
                saw_pre_reject = True

    assert saw_pre_reject, "PreToolUse hook 应至少 fire 一次且 fail"
