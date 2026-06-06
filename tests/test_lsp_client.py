"""pygls 适配层单元测试(spec §2.1 / §2.4)。

pygls 自身已处理 JSON-RPC 帧 / handshake / cancel / progress;Argos 包装层只需要:
- 暴露 `LspClient` 异步桥(server stdin/stdout ↔ asyncio)
- 暴露 `encode_frame(message: dict) -> bytes`(测试用,验 Content-Length UTF-8 字节数)
- 暴露 `parse_frames(stream: AsyncIterator[bytes]) -> AsyncIterator[dict]`(流式切帧)

本期不手写 framing 实现;直接委托 pygls。测试仅验 framing 边界 + 路由逻辑。"""
from __future__ import annotations

import asyncio
import json

import pytest

from argos_agent.lsp.client import encode_frame, parse_frames, LspClient, LspProtocolError


# ── encode_frame ────────────────────────────────────────────────────

def test_encode_frame_basic():
    """encode_frame({'jsonrpc': '2.0', 'id': 1, 'result': None}) → Content-Length 头 + body。"""
    msg = {"jsonrpc": "2.0", "id": 1, "result": None}
    encoded = encode_frame(msg)
    assert encoded.startswith(b"Content-Length: ")
    body = encoded.split(b"\r\n\r\n", 1)[1]
    assert json.loads(body) == msg


def test_encode_frame_utf8_byte_length():
    """Content-Length 按**字节**数,不是字符数(spec §4.2 中文 UTF-8 body 长度正确)。"""
    msg = {"jsonrpc": "2.0", "id": 1, "method": "foo", "params": {"text": "中文测试"}}
    encoded = encode_frame(msg)
    body = encoded.split(b"\r\n\r\n", 1)[1]
    expected_len = len(body)
    header = encoded.split(b"\r\n\r\n", 1)[0]
    actual_len = int(header.split(b":", 1)[1].strip())
    assert actual_len == expected_len
    assert expected_len > len("中文测试")  # UTF-8 字节 > 字符数


def test_encode_frame_empty_body():
    """空 body({}) → Content-Length: 2(只是 '{}')。"""
    encoded = encode_frame({})
    body = encoded.split(b"\r\n\r\n", 1)[1]
    assert body == b"{}"
    header = encoded.split(b"\r\n\r\n", 1)[0]
    assert b"Content-Length: 2" in header


# ── parse_frames ────────────────────────────────────────────────────

def test_parse_frames_single():
    """parse_frames 单帧 → 单 message。"""
    encoded = encode_frame({"jsonrpc": "2.0", "id": 1, "result": 42})
    msgs = list(_collect_sync(parse_frames(_async_iter([encoded]))))
    assert len(msgs) == 1
    assert msgs[0] == {"jsonrpc": "2.0", "id": 1, "result": 42}


def test_parse_frames_three_concatenated():
    """3 帧拼接 → 3 message(不丢字节)。"""
    e1 = encode_frame({"jsonrpc": "2.0", "id": 1, "result": 1})
    e2 = encode_frame({"jsonrpc": "2.0", "id": 2, "result": 2})
    e3 = encode_frame({"jsonrpc": "2.0", "id": 3, "result": 3})
    msgs = list(_collect_sync(parse_frames(_async_iter([e1 + e2 + e3]))))
    assert len(msgs) == 3
    assert [m["result"] for m in msgs] == [1, 2, 3]


def test_parse_frames_split_across_chunks():
    """1 帧被切成多块传输 → parse_frames 仍能切出。"""
    e = encode_frame({"jsonrpc": "2.0", "id": 1, "result": 99})
    chunks = [e[:10], e[10:50], e[50:]]
    msgs = list(_collect_sync(parse_frames(_async_iter(chunks))))
    assert len(msgs) == 1
    assert msgs[0]["result"] == 99


def test_parse_frames_long_body():
    """> 64KB 长 body → 不丢字节。"""
    big = "x" * (100 * 1024)
    e = encode_frame({"jsonrpc": "2.0", "id": 1, "method": "big", "params": {"text": big}})
    msgs = list(_collect_sync(parse_frames(_async_iter([e]))))
    assert len(msgs) == 1
    assert msgs[0]["params"]["text"] == big


def test_parse_frames_claimed_length_exceeds_eof_raises():
    """声称 length=100 但 EOF 提前 → 抛 LspProtocolError(manager 走 crash 路径)。"""
    fake = b"Content-Length: 100\r\n\r\n{short"
    with pytest.raises(LspProtocolError):
        list(_collect_sync(parse_frames(_async_iter([fake]))))


# ── helpers ────────────────────────────────────────────────────────

async def _async_iter(chunks):
    for c in chunks:
        yield c


def _collect_sync(agen):
    """把 async generator 跑到尽,返 list。"""
    out = []
    async def _run():
        async for x in agen:
            out.append(x)
    asyncio.run(_run())
    return out
