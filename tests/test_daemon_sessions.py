"""SessionRegistry 单元测试。"""
from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass

import pytest

from argos.daemon.sessions import HEARTBEAT_TIMEOUT_S, SessionRegistry


@pytest.mark.asyncio
async def test_create_session_returns_uuid():
    reg = SessionRegistry()
    rec = await reg.create()
    assert rec.session_id
    assert len(reg.list_active()) == 1


@pytest.mark.asyncio
async def test_heartbeat_extends_lifetime():
    reg = SessionRegistry(heartbeat_timeout_s=10.0)
    rec = await reg.create()
    rec.last_heartbeat = time.time() - 8
    ok = await reg.heartbeat(rec.session_id)
    assert ok
    assert reg.is_alive(rec.session_id)


@pytest.mark.asyncio
async def test_heartbeat_unknown_returns_false():
    reg = SessionRegistry()
    assert await reg.heartbeat("nonexistent") is False


@pytest.mark.asyncio
async def test_remove_session():
    reg = SessionRegistry()
    rec = await reg.create()
    await reg.remove(rec.session_id)
    assert not reg.is_alive(rec.session_id)


@pytest.mark.asyncio
async def test_active_count_excludes_expired():
    reg = SessionRegistry(heartbeat_timeout_s=0.5)
    rec = await reg.create()
    rec.last_heartbeat = time.time() - 1
    # 不 heartbeat → 应过期
    assert reg.active_count() == 0
    # heartbeat 续命
    await reg.heartbeat(rec.session_id)
    assert reg.active_count() == 1


@pytest.mark.asyncio
async def test_reap_expired():
    reg = SessionRegistry(heartbeat_timeout_s=0.5)
    rec = await reg.create()
    rec.last_heartbeat = time.time() - 1
    n = await reg.reap_expired()
    assert n == 1
    assert reg.active_count() == 0


@pytest.mark.asyncio
async def test_other_sessions_excludes_self():
    reg = SessionRegistry()
    a = await reg.create()
    b = await reg.create()
    others = reg.other_sessions(a.session_id)
    assert len(others) == 1
    assert others[0].session_id == b.session_id


@pytest.mark.asyncio
async def test_session_uuid_format():
    """session_id 是 UUID4 格式。"""
    import uuid
    reg = SessionRegistry()
    rec = await reg.create()
    # parse UUID
    uuid.UUID(rec.session_id)
