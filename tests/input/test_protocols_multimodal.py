"""protocols.py 多模态扩展 TDD 验收(spec §5)。

覆盖：
  - _coalesce_consecutive_roles 带 attachments 的合并行为
  - AnthropicProtocol.payload 图片块形状
  - OpenAIProtocol.payload 图片块形状
  - 无附件消息行为与现状逐字节一致(零回归)
"""
from __future__ import annotations

import base64

import pytest


def _att(data: bytes = b"\x89PNG\x00", media_type: str = "image/png",
          source_label: str = "test.png"):
    from argos.input.attachments import ImageAttachment
    return ImageAttachment(data=data, media_type=media_type, source_label=source_label)


def _tier(multimodal: bool = True):
    from argos.core.models import ModelTier
    return ModelTier(name="default", model="c", base_url="https://x", max_tokens=64,
                     multimodal=multimodal)


# ── _coalesce_consecutive_roles 扩展 ─────────────────────────────────────────

def test_coalesce_no_attachments_unchanged():
    """无 attachments 消息 → 行为与改造前一致(零回归)。"""
    from argos.core.protocols import _coalesce_consecutive_roles
    msgs = [
        {"role": "user", "content": "hi"},
        {"role": "assistant", "content": "hello"},
    ]
    result = _coalesce_consecutive_roles(msgs)
    assert result == [
        {"role": "user", "content": "hi"},
        {"role": "assistant", "content": "hello"},
    ]


def test_coalesce_consecutive_same_role_text_joined():
    """连续同 role 纯文本 → content 换行拼接(现有行为保留)。"""
    from argos.core.protocols import _coalesce_consecutive_roles
    msgs = [
        {"role": "user", "content": "a"},
        {"role": "user", "content": "b"},
    ]
    result = _coalesce_consecutive_roles(msgs)
    assert len(result) == 1
    assert result[0]["content"] == "a\nb"


def test_coalesce_consecutive_same_role_attachments_concat():
    """连续同 role 且有 attachments → attachments 列表拼接。"""
    from argos.core.protocols import _coalesce_consecutive_roles
    att1 = _att(b"A", source_label="a.png")
    att2 = _att(b"B", source_label="b.png")
    msgs = [
        {"role": "user", "content": "text1", "attachments": [att1]},
        {"role": "user", "content": "text2", "attachments": [att2]},
    ]
    result = _coalesce_consecutive_roles(msgs)
    assert len(result) == 1
    assert result[0]["content"] == "text1\ntext2"
    assert result[0]["attachments"] == [att1, att2]


def test_coalesce_attachment_message_followed_by_plain_different_role():
    """带 attachments 的 user 后接 assistant(不同 role)→ 不合并。"""
    from argos.core.protocols import _coalesce_consecutive_roles
    att = _att()
    msgs = [
        {"role": "user", "content": "img msg", "attachments": [att]},
        {"role": "assistant", "content": "ok"},
    ]
    result = _coalesce_consecutive_roles(msgs)
    assert len(result) == 2
    assert result[0]["attachments"] == [att]
    # assistant 消息无 attachments 字段
    assert "attachments" not in result[1]


# ── AnthropicProtocol.payload 图片块 ─────────────────────────────────────────

def test_anthropic_payload_no_attachments_content_is_plain_string():
    """无附件 → Anthropic payload messages[0]['content'] 仍是裸字符串(零回归)。"""
    from argos.core.protocols import AnthropicProtocol
    p = AnthropicProtocol()
    payload = p.payload(
        [{"role": "user", "content": "hello"}],
        system="S", tier=_tier(),
    )
    msg = payload["messages"][0]
    assert isinstance(msg["content"], str)
    assert msg["content"] == "hello"


def test_anthropic_payload_with_attachment_content_becomes_list():
    """带附件 → Anthropic payload message['content'] 变成 list(text + image blocks)。"""
    from argos.core.protocols import AnthropicProtocol
    att = _att(b"\x89PNG\x00\x00\x00", "image/png", "screen.png")
    p = AnthropicProtocol()
    payload = p.payload(
        [{"role": "user", "content": "see this", "attachments": [att]}],
        system="S", tier=_tier(multimodal=True),
    )
    content = payload["messages"][0]["content"]
    assert isinstance(content, list)
    # 第一块 = text
    assert content[0] == {"type": "text", "text": "see this"}
    # 第二块 = image
    img_block = content[1]
    assert img_block["type"] == "image"
    assert img_block["source"]["type"] == "base64"
    assert img_block["source"]["media_type"] == "image/png"
    expected_b64 = base64.b64encode(b"\x89PNG\x00\x00\x00").decode()
    assert img_block["source"]["data"] == expected_b64


def test_anthropic_payload_multiple_attachments():
    """多图附件 → content list 包含 1 text + N image blocks。"""
    from argos.core.protocols import AnthropicProtocol
    att1 = _att(b"A", "image/png", "a.png")
    att2 = _att(b"B", "image/jpeg", "b.jpg")
    p = AnthropicProtocol()
    payload = p.payload(
        [{"role": "user", "content": "two", "attachments": [att1, att2]}],
        system="S", tier=_tier(multimodal=True),
    )
    content = payload["messages"][0]["content"]
    assert len(content) == 3  # text + img1 + img2
    assert content[0]["type"] == "text"
    assert content[1]["type"] == "image"
    assert content[2]["type"] == "image"
    assert content[1]["source"]["media_type"] == "image/png"
    assert content[2]["source"]["media_type"] == "image/jpeg"


# ── OpenAIProtocol.payload 图片块 ────────────────────────────────────────────

def test_openai_payload_no_attachments_content_is_plain_string():
    """无附件 → OpenAI payload 用户消息 content 仍是裸字符串(零回归)。"""
    from argos.core.protocols import OpenAIProtocol
    p = OpenAIProtocol()
    payload = p.payload(
        [{"role": "user", "content": "hello"}],
        system="S", tier=_tier(),
    )
    # system 是第一条，用户是第二条
    user_msg = next(m for m in payload["messages"] if m["role"] == "user")
    assert isinstance(user_msg["content"], str)
    assert user_msg["content"] == "hello"


def test_openai_payload_with_attachment_content_becomes_list():
    """带附件 → OpenAI payload 用户消息 content 变成 list(text_url + image_url blocks)。"""
    from argos.core.protocols import OpenAIProtocol
    att = _att(b"\xff\xd8\xff\xe0", "image/jpeg", "photo.jpg")
    p = OpenAIProtocol()
    payload = p.payload(
        [{"role": "user", "content": "look", "attachments": [att]}],
        system="S", tier=_tier(multimodal=True),
    )
    user_msg = next(m for m in payload["messages"] if m["role"] == "user")
    content = user_msg["content"]
    assert isinstance(content, list)
    # 第一块 = text
    assert content[0] == {"type": "text", "text": "look"}
    # 第二块 = image_url (data URI)
    img_block = content[1]
    assert img_block["type"] == "image_url"
    expected_b64 = base64.b64encode(b"\xff\xd8\xff\xe0").decode()
    assert img_block["image_url"]["url"] == f"data:image/jpeg;base64,{expected_b64}"


def test_openai_payload_multiple_attachments():
    """多图附件 → content list 包含 1 text + N image_url blocks。"""
    from argos.core.protocols import OpenAIProtocol
    att1 = _att(b"A", "image/png", "a.png")
    att2 = _att(b"B", "image/webp", "b.webp")
    p = OpenAIProtocol()
    payload = p.payload(
        [{"role": "user", "content": "two", "attachments": [att1, att2]}],
        system="S", tier=_tier(multimodal=True),
    )
    user_msg = next(m for m in payload["messages"] if m["role"] == "user")
    content = user_msg["content"]
    assert len(content) == 3
    assert content[0]["type"] == "text"
    assert content[1]["type"] == "image_url"
    assert content[2]["type"] == "image_url"
    b64_a = base64.b64encode(b"A").decode()
    b64_b = base64.b64encode(b"B").decode()
    assert content[1]["image_url"]["url"] == f"data:image/png;base64,{b64_a}"
    assert content[2]["image_url"]["url"] == f"data:image/webp;base64,{b64_b}"
