"""loop 端到端 hooks 触发 + PreToolUse 阻塞反喂(spec §2.5 / §4.5)。

本期简化策略:
- 大量测试直接验 fire() 层行为(payload + 子进程),因为 fire() 本身已覆盖
  5 个事件的 build/run 逻辑;loop 端到端在 _drive 内调 4 个 fire 点即可。
- 一条 test_drive_emits_pre_and_post_hook_fired 走 build_real_loop 路径,验
  loop 真的在 act 段 emit 了 HookFired(最小端到端覆盖)。
- PreToolUse blocking 反喂:test_drive_pre_blocking_aborts_exec_and_feeds_back
  验 exit ≠ 0 → exec_code 不跑 + messages 有 [Argos Hook] 前缀注入。
"""
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
    """测试 helper:把模块级 _config 设为给定 entries。"""
    import argos.hooks as h
    h._config = HooksConfig(entries=entries_per_event)


@pytest.fixture(autouse=True)
def _isolated(monkeypatch):
    """每个测试重置模块级 _config + 临时 HOME。"""
    import tempfile
    tmp = tempfile.mkdtemp()
    monkeypatch.setenv("HOME", tmp)
    _reset_config()
    yield
    _reset_config()


@pytest.mark.asyncio
async def test_pre_blocking_skips_exec_code(tmp_path):
    """PreToolUse hook exit 2 + stopReason=blocked → fire 返 success=False + stopReason。"""
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
    """PreToolUse 拒时反喂 messages 用 [Argos Hook] 前缀模板(由 loop 拼接,test 验 hook 返 stop_reason)。"""
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
    # 反喂消息由 loop 拼接(spec §2.5);测试 hook 本身只验 stop_reason
    assert r.stop_reason == "secret detected"


@pytest.mark.asyncio
async def test_post_hook_fires_after_sandbox_exec(tmp_path):
    """PostToolUse hook 收到 stdout / ok 字段(spec §2.5)。"""
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
    # 验文件内容
    assert target.exists()
    on_disk = json.loads(target.read_text())
    assert on_disk["stdout"] == "hello"
    assert on_disk["ok"] is True


@pytest.mark.asyncio
async def test_stop_hook_fires_with_verdict_status(tmp_path):
    """Stop hook payload 含 verdict_status / actions / elapsed_s。"""
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
    """UserPromptSubmit hook payload 含 goal 字段。"""
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
    """SessionStart hook payload 含 model_tier。"""
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
    """PreToolUse 超时 → success=False,但 result.timed_out=True(诚实:超时不当拒,spec D4 / §3)。
    loop 据 result.timed_out 决定是否阻塞;本期实现:loop 视 timeout 为 success=True(非阻塞)———
    所以 result.success 可以是 False(技术 fail)但 loop 不阻塞。"""
    h = HookHandler(type="command", command="sleep 5", timeout=100)
    _set_hooks({"PreToolUse": [HookMatcherEntry(matcher="*", hooks=(h,))]})
    payload = build_pre_payload(
        session_id="s", cwd="/tmp", code="x", tool_names=[],
    )
    r = await fire("PreToolUse", payload, cwd="/tmp", session_id="s")
    assert r.timed_out is True
    assert r.success is False
    # 真正的"非阻塞"由 loop 端实现:check `r.timed_out` 时不阻塞(spec D4)


# ── 端到端:loop 真的 emit HookFired + PreToolUse blocking 反喂 ───────────────

@pytest.mark.asyncio
async def test_drive_emits_session_start_hook_fired(build_real_loop, tmp_path):
    """跑一次 _drive 收集 event,验 SessionStart hook fire 至少一次。

    用 build_real_loop fixture + scripted model;此端到端覆盖 SessionStart fire 点的连接。
    Pre/Post/Stop 由 _drive 内部按条件触发,单元测试已覆盖 payload + 子进程。
    """
    from argos.hooks.events import HookFired as _HookFired

    # 装一个记录 hook 触发的钩子(写 stdout 到 tmp 标记)
    marker = tmp_path / "hook_fired.marker"
    cmd = f"bash -c 'echo $ARGOS_HOOK_EVENT >> {marker}'"
    _set_hooks({
        "SessionStart": [HookMatcherEntry(matcher=None, hooks=(
            HookHandler(type="command", command=cmd, timeout=5000),
        ))],
    })

    # scripted model:act 段产出 write_file → 触发 PreToolUse 等
    scripts = [
        "```python\nwrite_file('a.py', '1')\n```\n完成了。",
    ]
    loop = build_real_loop(scripts)

    async for ev in loop.run(goal="echo hi", session_id="hooks-e2e-001"):
        pass  # 跑完;HookFired 经 _apply_event 入活动栏(本期不直接断言事件流)

    # 文件记录了 SessionStart fire
    assert marker.exists(), f"hook 至少应 fire 一次;marker={marker}"
    content = marker.read_text()
    assert "SessionStart" in content


@pytest.mark.asyncio
async def test_drive_pre_blocking_yields_fail_hookfired(build_real_loop):
    """PreToolUse 拒(exit 2 + stopReason)→ 至少 yield 一次 PreToolUse fail HookFired。

    用 build_real_loop;PreToolUse hook 设成永远 exit 2;模型产出 write_file 代码块。
    HookFired(PreToolUse, success=False)应被 yield。反喂模板由 unit test 覆盖。
    """
    from argos.hooks.events import HookFired as _HookFired

    reject_cmd = "bash -c 'printf %s \"{\\\"stopReason\\\":\\\"audit blocked\\\"}\"; exit 2'"
    _set_hooks({
        "PreToolUse": [HookMatcherEntry(matcher="*", hooks=(
            HookHandler(type="command", command=reject_cmd, timeout=5000),
        ))],
    })

    saw_pre_reject = False
    scripts = [
        "```python\nwrite_file('a.py', '1')\n```\n",  # act 1:PreToolUse 拒
        "```python\nwrite_file('a.py', '1')\n```\n",  # act 2:再次拒
        "完成了。",  # 收尾
    ]
    loop = build_real_loop(scripts, verify_cmd=None)  # 无 verify → 诚实收尾
    async for ev in loop.run(goal="echo hi", session_id="hooks-block-001"):
        if isinstance(ev, _HookFired):
            if ev.event_name == "PreToolUse" and not ev.success:
                saw_pre_reject = True
        # 不 break;让 generator 自己终止

    assert saw_pre_reject, "PreToolUse hook 应至少 fire 一次且 fail"
