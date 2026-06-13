# Multimodal Core + Image Attachments — Implementation Plan (Plan 1 of 3)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the engine backbone that lets a user message carry image attachments to a multimodal model, and honestly blocks the request when the routed model is text-only.

**Architecture:** Sidecar approach (spec §5, "方案 C"). Images ride in a parallel `attachments` field on the user message dict; `content` stays a plain string so the store, compaction, honesty checks, and `_coalesce_consecutive_roles` are untouched. Images materialize into wire format at exactly one place — the protocol adapter's `payload()`. A pre-send gate raises an honest error if attachments are present but the tier is not multimodal.

**Tech Stack:** Python 3.12, stdlib only (`base64`, `struct`, `pathlib`). No new pip dependencies in this plan. Tests: pytest.

**Scope note:** This plan is daemon- and TUI-agnostic — every task is unit-testable in isolation. The clipboard/TUI paste UX (Plan 2) and voice (Plan 3) build on top of this.

**Spec:** `docs/superpowers/specs/2026-06-13-voice-image-input-design.md` (§5, §4 `attachments.py` row, §13 criteria 2/4/5/6).

---

## File Structure

- `argos_agent/input/__init__.py` — new package marker (empty).
- `argos_agent/input/attachments.py` — `ImageAttachment`, `AttachmentError`, media-type sniffing, validation, base64, dimension sniffing, prompt path extraction. **One responsibility:** turning raw bytes/paths into validated image attachments. No network, no TUI.
- `argos_agent/core/models.py` — add `ModelTier.multimodal` capability flag.
- `argos_agent/core/protocols.py` — image-block helpers, attachment-aware `_coalesce_consecutive_roles`, attachment materialization in both `payload()` methods.
- `argos_agent/core/loop.py` — `build_user_message`, `multimodal_gate`, `MultimodalUnsupportedError`; thread `attachments` through `run`/`_drive`.
- Tests (new files, additive): `tests/input/test_attachments.py`, `tests/test_models_multimodal.py`, `tests/test_protocols_attachments.py`, `tests/test_loop_attachments.py`.

---

## Task 1: `ImageAttachment` + media-type sniffing

**Files:**
- Create: `argos_agent/input/__init__.py`
- Create: `argos_agent/input/attachments.py`
- Test: `tests/input/test_attachments.py`

- [ ] **Step 1: Write the failing test**

Create `tests/input/test_attachments.py`:

```python
"""input/attachments.py — 图片附件数据 + 嗅探/校验/编码(纯逻辑,无网络)。"""
from argos_agent.input.attachments import (
    ImageAttachment, AttachmentError, sniff_media_type,
    SUPPORTED_MEDIA_TYPES, MAX_IMAGE_BYTES,
)

_PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32
_JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 16
_GIF = b"GIF89a" + b"\x00" * 16
_WEBP = b"RIFF" + b"\x00\x00\x00\x00" + b"WEBP" + b"\x00" * 8


def test_sniff_png():
    assert sniff_media_type(_PNG) == "image/png"

def test_sniff_jpeg():
    assert sniff_media_type(_JPEG) == "image/jpeg"

def test_sniff_gif():
    assert sniff_media_type(_GIF) == "image/gif"

def test_sniff_webp():
    assert sniff_media_type(_WEBP) == "image/webp"

def test_sniff_unknown_returns_none():
    assert sniff_media_type(b"not an image") is None

def test_attachment_is_frozen():
    att = ImageAttachment(data=_PNG, media_type="image/png", source_label="x")
    import dataclasses
    try:
        att.media_type = "image/jpeg"
        assert False, "should be frozen"
    except dataclasses.FrozenInstanceError:
        pass

def test_supported_set_and_limit_constants():
    assert "image/png" in SUPPORTED_MEDIA_TYPES
    assert MAX_IMAGE_BYTES == 5 * 1024 * 1024
    # AttachmentError 是 Exception 子类
    assert issubclass(AttachmentError, Exception)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/input/test_attachments.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'argos_agent.input'`

- [ ] **Step 3: Write minimal implementation**

Create `argos_agent/input/__init__.py` (empty file):

```python
```

Create `argos_agent/input/attachments.py`:

```python
"""图片附件:原始字节/路径 → 校验过的 ImageAttachment(纯逻辑,无网络、无 TUI)。

诚实边界:格式不认 → 返回 None / 抛 AttachmentError,绝不静默当成图。
"""
from __future__ import annotations

from dataclasses import dataclass

# Anthropic / OpenAI 都支持的图像类型(对齐 Claude Code:png/jpeg/gif/webp)。
SUPPORTED_MEDIA_TYPES: frozenset[str] = frozenset(
    {"image/png", "image/jpeg", "image/gif", "image/webp"}
)
# 单张上限 5MB(对齐 Claude Code / Anthropic 端点)。
MAX_IMAGE_BYTES: int = 5 * 1024 * 1024


class AttachmentError(Exception):
    """附件非法:格式不支持 / 超过体积上限 / 路径不是图片。"""


@dataclass(frozen=True, slots=True)
class ImageAttachment:
    """一张图片附件。data=原始字节;media_type=嗅探出的 MIME;source_label=给 UI/transcript 的标签。
    width/height best-effort(嗅探不出留 None,诚实)。"""

    data: bytes
    media_type: str
    source_label: str
    width: int | None = None
    height: int | None = None


def sniff_media_type(data: bytes) -> str | None:
    """按 magic bytes 嗅探图片类型。不认 → None(诚实,不猜)。"""
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"
    if data[:3] == b"\xff\xd8\xff":
        return "image/jpeg"
    if data[:6] in (b"GIF87a", b"GIF89a"):
        return "image/gif"
    if len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    return None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/input/test_attachments.py -v`
Expected: PASS (8 passed)

- [ ] **Step 5: Commit**

```bash
git add argos_agent/input/__init__.py argos_agent/input/attachments.py tests/input/test_attachments.py
git commit -m "feat(input): ImageAttachment + media-type sniffing"
```

---

## Task 2: validation, base64, dimension sniffing

**Files:**
- Modify: `argos_agent/input/attachments.py`
- Test: `tests/input/test_attachments.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/input/test_attachments.py`:

```python
from argos_agent.input.attachments import (
    validate_attachment, to_base64, sniff_dimensions,
)
import base64 as _b64
import struct


def _png_with_dims(w: int, h: int) -> bytes:
    # 8B 签名 + IHDR 长度(4B)+ "IHDR"(4B)+ width(4B BE)+ height(4B BE)+ 余
    return (b"\x89PNG\r\n\x1a\n" + b"\x00\x00\x00\x0dIHDR"
            + struct.pack(">II", w, h) + b"\x00" * 5)


def _gif_with_dims(w: int, h: int) -> bytes:
    return b"GIF89a" + struct.pack("<HH", w, h) + b"\x00" * 8


def test_validate_accepts_png():
    att = ImageAttachment(data=_PNG, media_type="image/png", source_label="x")
    validate_attachment(att)  # 不抛即通过

def test_validate_rejects_unsupported_type():
    att = ImageAttachment(data=b"x", media_type="image/tiff", source_label="x")
    try:
        validate_attachment(att)
        assert False
    except AttachmentError as e:
        assert "tiff" in str(e) or "支持" in str(e)

def test_validate_rejects_oversize():
    big = ImageAttachment(data=b"\x00" * (MAX_IMAGE_BYTES + 1),
                          media_type="image/png", source_label="x")
    try:
        validate_attachment(big)
        assert False
    except AttachmentError as e:
        assert "5" in str(e) or "MB" in str(e) or "大" in str(e)

def test_to_base64_roundtrips():
    att = ImageAttachment(data=_PNG, media_type="image/png", source_label="x")
    assert _b64.b64decode(to_base64(att)) == _PNG

def test_sniff_dimensions_png():
    assert sniff_dimensions(_png_with_dims(1280, 720)) == (1280, 720)

def test_sniff_dimensions_gif():
    assert sniff_dimensions(_gif_with_dims(64, 48)) == (64, 48)

def test_sniff_dimensions_unknown_returns_none():
    assert sniff_dimensions(_JPEG) is None  # JPEG 维度本期不解析,诚实返回 None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/input/test_attachments.py -k "validate or base64 or dimensions" -v`
Expected: FAIL — `ImportError: cannot import name 'validate_attachment'`

- [ ] **Step 3: Write minimal implementation**

Append to `argos_agent/input/attachments.py`:

```python
import base64
import struct


def validate_attachment(att: ImageAttachment) -> None:
    """校验:类型在白名单 + 体积不超上限。违规抛 AttachmentError(诚实,带原因)。"""
    if att.media_type not in SUPPORTED_MEDIA_TYPES:
        raise AttachmentError(
            f"不支持的图片类型 {att.media_type};仅支持 "
            f"{', '.join(sorted(SUPPORTED_MEDIA_TYPES))}"
        )
    if len(att.data) > MAX_IMAGE_BYTES:
        mb = MAX_IMAGE_BYTES // (1024 * 1024)
        raise AttachmentError(
            f"图片过大({len(att.data)} 字节),单张上限 {mb}MB"
        )


def to_base64(att: ImageAttachment) -> str:
    """原始字节 → base64 字符串(供协议层拼 wire 块)。"""
    return base64.b64encode(att.data).decode("ascii")


def sniff_dimensions(data: bytes) -> tuple[int, int] | None:
    """best-effort 读宽高。PNG / GIF 可读;其它(jpeg/webp)本期返回 None(诚实,不猜)。"""
    # PNG:8B 签名 + 4B 长度 + "IHDR" + 4B width(BE) + 4B height(BE)
    if data[:8] == b"\x89PNG\r\n\x1a\n" and len(data) >= 24 and data[12:16] == b"IHDR":
        w, h = struct.unpack(">II", data[16:24])
        return int(w), int(h)
    # GIF:6B 签名 + 2B width(LE) + 2B height(LE)
    if data[:6] in (b"GIF87a", b"GIF89a") and len(data) >= 10:
        w, h = struct.unpack("<HH", data[6:10])
        return int(w), int(h)
    return None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/input/test_attachments.py -v`
Expected: PASS (15 passed total)

- [ ] **Step 5: Commit**

```bash
git add argos_agent/input/attachments.py tests/input/test_attachments.py
git commit -m "feat(input): attachment validation + base64 + dimension sniff"
```

---

## Task 3: prompt path extraction + load from disk

**Files:**
- Modify: `argos_agent/input/attachments.py`
- Test: `tests/input/test_attachments.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/input/test_attachments.py`:

```python
from argos_agent.input.attachments import extract_image_paths, load_image_path


def test_extract_image_paths_finds_existing_image(tmp_path):
    p = tmp_path / "shot.png"
    p.write_bytes(_png_with_dims(10, 10))
    text = f"看这张 {p} 按钮歪了"
    assert str(p) in extract_image_paths(text)

def test_extract_image_paths_ignores_nonexistent(tmp_path):
    text = f"{tmp_path / 'nope.png'} 不存在"
    assert extract_image_paths(text) == []

def test_extract_image_paths_ignores_nonimage(tmp_path):
    p = tmp_path / "notes.txt"
    p.write_text("hi")
    assert extract_image_paths(str(p)) == []

def test_load_image_path_sniffs_and_validates(tmp_path):
    p = tmp_path / "shot.png"
    p.write_bytes(_png_with_dims(1280, 720))
    att = load_image_path(str(p))
    assert att.media_type == "image/png"
    assert att.width == 1280 and att.height == 720
    assert att.source_label == "shot.png"

def test_load_image_path_rejects_nonimage(tmp_path):
    p = tmp_path / "notes.txt"
    p.write_text("hi")
    try:
        load_image_path(str(p))
        assert False
    except AttachmentError:
        pass
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/input/test_attachments.py -k "extract or load_image" -v`
Expected: FAIL — `ImportError: cannot import name 'extract_image_paths'`

- [ ] **Step 3: Write minimal implementation**

Append to `argos_agent/input/attachments.py`:

```python
import re
from pathlib import Path

# 候选路径 token:含图片后缀,可带引号/反斜杠转义空格。宽松抓取,存在性由 Path 判。
_PATH_RE = re.compile(r"""["']?((?:[^\s"']|\\ )+\.(?:png|jpe?g|gif|webp))["']?""",
                      re.IGNORECASE)


def extract_image_paths(text: str) -> list[str]:
    """从 prompt 文本里抠出【存在的图片文件路径】(终端拖文件会粘成路径)。
    不存在 / 非图片后缀 → 不收(诚实)。"""
    out: list[str] = []
    for m in _PATH_RE.finditer(text or ""):
        raw = m.group(1).replace("\\ ", " ")
        if Path(raw).is_file() and raw not in out:
            out.append(raw)
    return out


def load_image_path(path: str) -> ImageAttachment:
    """读盘 → 嗅探类型/宽高 → 校验 → ImageAttachment。非图片 / 非法 → AttachmentError。"""
    data = Path(path).read_bytes()
    media = sniff_media_type(data)
    if media is None:
        raise AttachmentError(f"{path} 不是受支持的图片格式")
    dims = sniff_dimensions(data)
    att = ImageAttachment(
        data=data, media_type=media, source_label=Path(path).name,
        width=dims[0] if dims else None, height=dims[1] if dims else None,
    )
    validate_attachment(att)
    return att
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/input/test_attachments.py -v`
Expected: PASS (20 passed total)

- [ ] **Step 5: Commit**

```bash
git add argos_agent/input/attachments.py tests/input/test_attachments.py
git commit -m "feat(input): image path extraction + load_image_path"
```

---

## Task 4: `ModelTier.multimodal` capability flag

**Files:**
- Modify: `argos_agent/core/models.py:30-31`
- Test: `tests/test_models_multimodal.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_models_multimodal.py`:

```python
"""ModelTier.multimodal 能力位:默认 False(零破坏既有构造点),可显式开。"""
from argos_agent.core.models import ModelTier


def test_multimodal_defaults_false():
    t = ModelTier(name="worker", model="m", base_url="u", max_tokens=2048)
    assert t.multimodal is False

def test_multimodal_can_be_set():
    t = ModelTier(name="worker", model="m", base_url="u", max_tokens=2048,
                  multimodal=True)
    assert t.multimodal is True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_models_multimodal.py -v`
Expected: FAIL — `TypeError: __init__() got an unexpected keyword argument 'multimodal'`

- [ ] **Step 3: Write minimal implementation**

In `argos_agent/core/models.py`, the `ModelTier` dataclass currently ends:

```python
    context_window: int = 200_000
    protocol: str = "anthropic"   # "anthropic" | "openai";默认值保旧构造点/旧 env 回退零破坏
```

Add one field after `protocol`:

```python
    context_window: int = 200_000
    protocol: str = "anthropic"   # "anthropic" | "openai";默认值保旧构造点/旧 env 回退零破坏
    multimodal: bool = False      # 模型是否支持图像输入(setup 探针/config 填);默认 False = 纯文本,零破坏
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_models_multimodal.py -v`
Expected: PASS (2 passed)

- [ ] **Step 5: Commit**

```bash
git add argos_agent/core/models.py tests/test_models_multimodal.py
git commit -m "feat(models): ModelTier.multimodal capability flag (default False)"
```

---

## Task 5: protocol image-block helpers + attachment-aware coalesce

**Files:**
- Modify: `argos_agent/core/protocols.py:10-21` (`_coalesce_consecutive_roles`)
- Modify: `argos_agent/core/protocols.py` (add module-level helpers near top)
- Test: `tests/test_protocols_attachments.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_protocols_attachments.py`:

```python
"""协议层附件:image block 形状 + coalesce 带附件 + materialize。"""
from argos_agent.core.protocols import (
    _coalesce_consecutive_roles, _anthropic_image_block, _openai_image_block,
    _materialize_attachments,
)
from argos_agent.input.attachments import ImageAttachment

_ATT = ImageAttachment(data=b"\x89PNG\r\n\x1a\n", media_type="image/png",
                       source_label="s.png")


def test_anthropic_image_block_shape():
    b = _anthropic_image_block(_ATT)
    assert b["type"] == "image"
    assert b["source"]["type"] == "base64"
    assert b["source"]["media_type"] == "image/png"
    assert isinstance(b["source"]["data"], str) and b["source"]["data"]

def test_openai_image_block_shape():
    b = _openai_image_block(_ATT)
    assert b["type"] == "image_url"
    assert b["image_url"]["url"].startswith("data:image/png;base64,")

def test_coalesce_text_only_unchanged():
    # 无附件:行为与改造前逐字一致,且不冒出 attachments key
    msgs = [{"role": "user", "content": "a"}, {"role": "user", "content": "b"}]
    out = _coalesce_consecutive_roles(msgs)
    assert out == [{"role": "user", "content": "a\nb"}]
    assert "attachments" not in out[0]

def test_coalesce_carries_attachments():
    msgs = [
        {"role": "user", "content": "a", "attachments": [_ATT]},
        {"role": "user", "content": "b"},
    ]
    out = _coalesce_consecutive_roles(msgs)
    assert out[0]["content"] == "a\nb"
    assert out[0]["attachments"] == [_ATT]

def test_materialize_text_only_passthrough():
    msgs = [{"role": "user", "content": "hi"}]
    assert _materialize_attachments(msgs, _anthropic_image_block) == msgs

def test_materialize_builds_block_list():
    msgs = [{"role": "user", "content": "look", "attachments": [_ATT]}]
    out = _materialize_attachments(msgs, _anthropic_image_block)
    assert out[0]["content"][0] == {"type": "text", "text": "look"}
    assert out[0]["content"][1]["type"] == "image"
    assert "attachments" not in out[0]  # wire 消息不留 attachments key
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_protocols_attachments.py -v`
Expected: FAIL — `ImportError: cannot import name '_anthropic_image_block'`

- [ ] **Step 3: Write minimal implementation**

In `argos_agent/core/protocols.py`, replace `_coalesce_consecutive_roles` (lines 10-21) with this attachment-aware version and add the three helpers right after it:

```python
def _coalesce_consecutive_roles(messages: list[dict]) -> list[dict]:
    """合并连续同 role 的消息,保证 user/assistant 交替(Anthropic 兼容端要求,否则 400)。
    多轮/压缩会产生连续同 role;发请求前把相邻同 role content 用换行并起来(I1 修复)。
    带 attachments 的消息:文本照旧并接,attachments 列表一并 extend;无附件路径输出逐字不变。"""
    out: list[dict] = []
    for m in messages:
        role = m.get("role")
        content = m.get("content", "")
        atts = m.get("attachments") or []
        if out and out[-1]["role"] == role:
            out[-1]["content"] = f"{out[-1]['content']}\n{content}"
            if atts:
                out[-1]["attachments"] = list(out[-1].get("attachments", [])) + list(atts)
        else:
            new: dict = {"role": role, "content": content}
            if atts:
                new["attachments"] = list(atts)
            out.append(new)
    return out


def _anthropic_image_block(att) -> dict:
    """ImageAttachment → Anthropic image content block(base64 source)。"""
    from argos_agent.input.attachments import to_base64
    return {
        "type": "image",
        "source": {"type": "base64", "media_type": att.media_type, "data": to_base64(att)},
    }


def _openai_image_block(att) -> dict:
    """ImageAttachment → OpenAI image_url content block(data URI)。"""
    from argos_agent.input.attachments import to_base64
    return {
        "type": "image_url",
        "image_url": {"url": f"data:{att.media_type};base64,{to_base64(att)}"},
    }


def _materialize_attachments(messages: list[dict], block_fn) -> list[dict]:
    """把带 attachments 的消息物化成 [text block, image block...] 的 content 列表;
    无附件消息原样透传(content 仍是裸字符串 → wire payload 与现状逐字节一致)。
    wire 消息不保留 attachments key。"""
    out: list[dict] = []
    for m in messages:
        atts = m.get("attachments")
        if atts:
            blocks = [{"type": "text", "text": m.get("content") or ""}]
            blocks.extend(block_fn(a) for a in atts)
            out.append({"role": m["role"], "content": blocks})
        else:
            out.append(m)
    return out
```

(The `from argos_agent.input.attachments import to_base64` is a local import inside the helpers to avoid any import-order coupling; `input.attachments` imports nothing from `core`, so there is no cycle.)

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_protocols_attachments.py -v`
Expected: PASS (7 passed)

- [ ] **Step 5: Run the existing protocol tests to confirm zero regression**

Run: `uv run pytest -k "protocol or payload or coalesce" -v`
Expected: PASS (all existing protocol/payload tests still green)

- [ ] **Step 6: Commit**

```bash
git add argos_agent/core/protocols.py tests/test_protocols_attachments.py
git commit -m "feat(protocols): image-block helpers + attachment-aware coalesce"
```

---

## Task 6: Anthropic `payload()` materializes attachments

**Files:**
- Modify: `argos_agent/core/protocols.py:48-74` (`AnthropicProtocol.payload`)
- Test: `tests/test_protocols_attachments.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_protocols_attachments.py`:

```python
from argos_agent.core.protocols import AnthropicProtocol


class _Tier:
    model = "claude"
    max_tokens = 2048


def test_anthropic_payload_no_attachment_keeps_string_content():
    p = AnthropicProtocol().payload(
        [{"role": "user", "content": "hi"}], system="sys", tier=_Tier())
    assert p["messages"] == [{"role": "user", "content": "hi"}]  # 逐字节不变

def test_anthropic_payload_with_attachment_emits_blocks():
    p = AnthropicProtocol().payload(
        [{"role": "user", "content": "look", "attachments": [_ATT]}],
        system="sys", tier=_Tier())
    content = p["messages"][0]["content"]
    assert content[0] == {"type": "text", "text": "look"}
    assert content[1]["type"] == "image"
    assert "attachments" not in p["messages"][0]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_protocols_attachments.py -k anthropic_payload -v`
Expected: FAIL — `assert content[1]["type"] == "image"` raises (content is still the plain string today)

- [ ] **Step 3: Write minimal implementation**

In `AnthropicProtocol.payload`, the return currently is:

```python
        return {
            "model": tier.model,
            "max_tokens": tier.max_tokens,
            "system": system_blocks,
            "messages": _coalesce_consecutive_roles(messages),
            "stream": True,
        }
```

Change the `messages` line to materialize attachments after coalescing:

```python
        return {
            "model": tier.model,
            "max_tokens": tier.max_tokens,
            "system": system_blocks,
            "messages": _materialize_attachments(
                _coalesce_consecutive_roles(messages), _anthropic_image_block),
            "stream": True,
        }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_protocols_attachments.py -k anthropic_payload -v`
Expected: PASS (2 passed)

- [ ] **Step 5: Commit**

```bash
git add argos_agent/core/protocols.py tests/test_protocols_attachments.py
git commit -m "feat(protocols): Anthropic payload materializes image attachments"
```

---

## Task 7: OpenAI `payload()` materializes attachments

**Files:**
- Modify: `argos_agent/core/protocols.py:119-136` (`OpenAIProtocol.payload`)
- Test: `tests/test_protocols_attachments.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_protocols_attachments.py`:

```python
from argos_agent.core.protocols import OpenAIProtocol


def test_openai_payload_no_attachment_keeps_string_content():
    p = OpenAIProtocol().payload(
        [{"role": "user", "content": "hi"}], system="sys", tier=_Tier())
    # 首条是 system,其后是 user(content 仍是裸字符串)
    assert p["messages"][1] == {"role": "user", "content": "hi"}

def test_openai_payload_with_attachment_emits_image_url():
    p = OpenAIProtocol().payload(
        [{"role": "user", "content": "look", "attachments": [_ATT]}],
        system="sys", tier=_Tier())
    content = p["messages"][1]["content"]
    assert content[0] == {"type": "text", "text": "look"}
    assert content[1]["type"] == "image_url"
    assert content[1]["image_url"]["url"].startswith("data:image/png;base64,")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_protocols_attachments.py -k openai_payload -v`
Expected: FAIL — content is still the plain string

- [ ] **Step 3: Write minimal implementation**

In `OpenAIProtocol.payload`, the body currently is:

```python
        msgs: list[dict] = [{"role": "system", "content": system_content}]
        msgs.extend(_coalesce_consecutive_roles(messages))
        return {
```

Change the `extend` line to materialize attachments:

```python
        msgs: list[dict] = [{"role": "system", "content": system_content}]
        msgs.extend(_materialize_attachments(
            _coalesce_consecutive_roles(messages), _openai_image_block))
        return {
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_protocols_attachments.py -k openai_payload -v`
Expected: PASS (2 passed)

- [ ] **Step 5: Commit**

```bash
git add argos_agent/core/protocols.py tests/test_protocols_attachments.py
git commit -m "feat(protocols): OpenAI payload materializes image attachments"
```

---

## Task 8: loop threads attachments + honest multimodal gate

**Files:**
- Modify: `argos_agent/core/loop.py` (add module-level `MultimodalUnsupportedError`, `build_user_message`, `multimodal_gate`; thread `attachments` through `run` at `loop.py:712` and the first-message build at `loop.py:1060`)
- Test: `tests/test_loop_attachments.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_loop_attachments.py`:

```python
"""loop 附件管线:消息构造 + 多模态诚实门(纯函数,无需实例化重 loop)。"""
import pytest
from argos_agent.core.loop import (
    build_user_message, multimodal_gate, MultimodalUnsupportedError,
)
from argos_agent.input.attachments import ImageAttachment

_ATT = ImageAttachment(data=b"\x89PNG\r\n\x1a\n", media_type="image/png",
                       source_label="s.png")


def test_build_user_message_text_only_has_no_attachments_key():
    msg = build_user_message("做点事", None)
    assert msg == {"role": "user", "content": "做点事"}
    assert "attachments" not in msg

def test_build_user_message_with_attachments():
    msg = build_user_message("看图", [_ATT])
    assert msg["content"] == "看图"
    assert msg["attachments"] == [_ATT]

def test_multimodal_gate_passes_when_no_attachments():
    multimodal_gate(tier_multimodal=False, has_attachments=False)  # 不抛

def test_multimodal_gate_passes_when_tier_multimodal():
    multimodal_gate(tier_multimodal=True, has_attachments=True)  # 不抛

def test_multimodal_gate_blocks_text_only_with_attachment():
    with pytest.raises(MultimodalUnsupportedError):
        multimodal_gate(tier_multimodal=False, has_attachments=True)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_loop_attachments.py -v`
Expected: FAIL — `ImportError: cannot import name 'build_user_message'`

- [ ] **Step 3: Write minimal implementation**

In `argos_agent/core/loop.py`, add near the top-level definitions (after imports, before `class AgentLoop`):

```python
class MultimodalUnsupportedError(Exception):
    """带图请求但路由模型纯文本:诚实阻断,绝不静默剥图。"""


def build_user_message(goal: str, attachments=None) -> dict:
    """构造首条 user 消息。无附件 → 不加 attachments key(wire payload 逐字节不变);
    有附件 → 挂边车字段(content 仍是字符串)。"""
    msg: dict = {"role": "user", "content": goal}
    if attachments:
        msg["attachments"] = list(attachments)
    return msg


def multimodal_gate(*, tier_multimodal: bool, has_attachments: bool) -> None:
    """发请求前的诚实门:有附件但模型纯文本 → 抛 MultimodalUnsupportedError。"""
    if has_attachments and not tier_multimodal:
        raise MultimodalUnsupportedError(
            "当前模型不支持图像输入,请在 setup 配置一个多模态模型。"
        )
```

Then thread `attachments` through `run` and `_drive`. Change the `run` signature at `loop.py:712`:

```python
    async def run(self, goal: str, session_id: str, attachments=None) -> AsyncIterator["Event"]:
```

Inside `run`, the call to `_drive` (currently `async for ev in self._drive(goal, session_id):` at `loop.py:746`) sits inside the top-level `try`. Add the gate immediately before that loop, and pass attachments through:

```python
        try:
            multimodal_gate(
                tier_multimodal=getattr(self._model.tier, "multimodal", False),
                has_attachments=bool(attachments),
            )
            async for ev in self._drive(goal, session_id, attachments):
                self._store.append_event(session_id, ev)
                yield ev
        except Exception as e:  # noqa: BLE001
```

(The existing `except Exception` handler already builds the chain and yields `Error(message=str(e), chain=chain)`, so `MultimodalUnsupportedError` surfaces as an honest `Error` event — no new event plumbing needed.)

Update the `_drive` signature to accept `attachments=None` (find `async def _drive(self, goal` / `def _drive(self, goal`) and replace the first-message build at `loop.py:1060`:

```python
        messages.append({"role": "user", "content": goal})
```

with:

```python
        messages.append(build_user_message(goal, attachments))
```

(Leave `self._store.append_message(session_id, role="user", content=goal)` on the next line unchanged — the store keeps text only; attachments are not persisted as bytes, which keeps the transcript readable.)

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_loop_attachments.py -v`
Expected: PASS (5 passed)

- [ ] **Step 5: Run the full loop suite to confirm zero regression**

Run: `uv run pytest tests/test_loop.py -v`
Expected: PASS (existing loop tests still green; `run`/`_drive` new arg is optional)

- [ ] **Step 6: Commit**

```bash
git add argos_agent/core/loop.py tests/test_loop_attachments.py
git commit -m "feat(loop): thread image attachments + honest multimodal gate"
```

---

## Task 9: full-suite verification gate

**Files:** none (verification only)

- [ ] **Step 1: Run the full suite with coverage**

Run: `uv run pytest -n auto --dist loadgroup`
Expected: all green, coverage ≥ 80% (coverage gate is on the full suite, per CLAUDE.md).

- [ ] **Step 2: If coverage dipped below 80%**

The new `argos_agent/input/attachments.py` is fully covered by `tests/input/test_attachments.py`. If total coverage is under 80%, it is almost certainly an unrelated pre-existing gap — confirm by running `uv run pytest` (serial) and reading the coverage report's `Missing` column for `argos_agent/input/` and the touched `core/` files. Add targeted tests only for lines this plan introduced.

- [ ] **Step 3: No commit** (verification only). If new tests were added in Step 2, commit them:

```bash
git add tests/
git commit -m "test: cover remaining multimodal-core branches"
```

---

## Self-Review

**Spec coverage (against `2026-06-13-voice-image-input-design.md` §5):**
- "边车 `attachments` 字段，`content` 保持字符串" → Tasks 1-3 (ImageAttachment), Task 8 (build_user_message keeps content a string). ✅
- "`ModelTier` 增能力位 `multimodal`" → Task 4. ✅
- "`_coalesce_consecutive_roles` 处理 attachments，无附件路径逐字不变" → Task 5 (`test_coalesce_text_only_unchanged`). ✅
- "图片只在 `payload()` 一处物化；Anthropic `image`/base64 + OpenAI `image_url`" → Tasks 5-7. ✅
- "无附件的消息行为与现状逐字节一致" → Tasks 6-7 (`*_no_attachment_keeps_string_content`). ✅ (spec §13 criterion 6)
- "诚实门禁：纯文本 tier + 附件 → 诚实阻断" → Task 8 (`multimodal_gate`). ✅ (spec §13 criterion 5)
- "格式(png/jpeg/webp/gif) + 单张 ≤5MB 校验" → Task 2. ✅
- "prompt 内图片路径检测" → Task 3. ✅ (spec §13 criterion 4 — detection half; the submit-time wiring is Plan 2)

**Out of scope here (Plan 2 / Plan 3, intentionally):** clipboard read, TUI paste pipeline/chips, `Ctrl+V`, submit-expand, daemon attachment transport, voice. These are listed so no reviewer mistakes them for gaps in *this* plan.

**Placeholder scan:** No TBD/TODO; every code step shows complete code. ✅

**Type consistency:** `ImageAttachment(data, media_type, source_label, width, height)` used identically in Tasks 1, 3, 5, 8. `_anthropic_image_block`/`_openai_image_block`/`_materialize_attachments`/`_coalesce_consecutive_roles` signatures match between definition (Task 5) and use (Tasks 6-7). `build_user_message(goal, attachments)` and `multimodal_gate(*, tier_multimodal, has_attachments)` defined and called consistently (Task 8). ✅

---

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-06-13-multimodal-core-and-attachments.md`. Two execution options:

1. **Subagent-Driven (recommended)** — fresh subagent per task, two-stage review between tasks, fast iteration.
2. **Inline Execution** — execute tasks in this session via executing-plans, batch with checkpoints.

This is **Plan 1 of 3**. Plans 2 (image input UX: clipboard + TUI paste pipeline + daemon transport) and 3 (voice: recorder + STT + space-to-record + packaging) build on this backbone and will be written next.
