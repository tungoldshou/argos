"""Internal documentation."""
from __future__ import annotations

import base64
import json

import pytest

from argos.core.loop import AgentLoop

_PNG_1x1 = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAAC0lEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="
)


def _loop_with_vision(capable: bool | None) -> AgentLoop:
    loop = object.__new__(AgentLoop)
    loop._vision_capable = capable  # type: ignore[attr-defined]
    return loop


def test_attach_when_capable(tmp_path):
    png = tmp_path / "shot.png"
    png.write_bytes(_PNG_1x1)
    loop = _loop_with_vision(True)
    fb = {"role": "user", "content": "执行结果"}
    loop._maybe_attach_screenshot(fb, (str(png), (120, 80)))
    assert "attachments" in fb and len(fb["attachments"]) == 1
    assert fb["attachments"][0].media_type == "image/png"
    assert "120x80" in fb["content"]
    assert "像素坐标" in fb["content"]
    assert not png.exists()


def test_no_attach_when_not_capable(tmp_path):
    png = tmp_path / "shot.png"
    png.write_bytes(_PNG_1x1)
    loop = _loop_with_vision(False)
    fb = {"role": "user", "content": "执行结果"}
    loop._maybe_attach_screenshot(fb, (str(png), (120, 80)))
    assert "attachments" not in fb
    assert fb["content"] == "执行结果"


def test_no_attach_when_capability_unresolved(tmp_path):
    png = tmp_path / "shot.png"
    png.write_bytes(_PNG_1x1)
    loop = _loop_with_vision(None)
    fb = {"role": "user", "content": "x"}
    loop._maybe_attach_screenshot(fb, (str(png), (10, 10)))
    assert "attachments" not in fb


def test_no_shot_is_noop(tmp_path):
    loop = _loop_with_vision(True)
    fb = {"role": "user", "content": "x"}
    loop._maybe_attach_screenshot(fb, None)
    assert "attachments" not in fb
    assert fb["content"] == "x"


def test_unreadable_path_degrades_to_text(tmp_path):
    loop = _loop_with_vision(True)
    fb = {"role": "user", "content": "执行结果"}
    loop._maybe_attach_screenshot(fb, (str(tmp_path / "missing.png"), (10, 10)))
    assert "attachments" not in fb
    assert fb["content"] == "执行结果"


@pytest.mark.asyncio
async def test_resolve_warms_from_cache_for_computer_use(monkeypatch, tmp_path):
    monkeypatch.setenv("ARGOS_COMPUTER_USE", "1")
    monkeypatch.setenv("ARGOS_CONFIG_DIR", str(tmp_path))
    (tmp_path / "vision_cache.json").write_text(
        json.dumps({"https://api.x/v1": {"m1": {"verified": True, "ts": 0}}})
    )
    loop = object.__new__(AgentLoop)

    class _Tier:
        multimodal = None
        base_url = "https://api.x/v1"
        model = "m1"

    class _Model:
        tier = _Tier()

    loop._model = _Model()  # type: ignore[attr-defined]
    await loop._resolve_vision_capable(None)
    assert loop._vision_capable is True


@pytest.mark.asyncio
async def test_resolve_skipped_for_plain_text_run(monkeypatch):
    monkeypatch.delenv("ARGOS_COMPUTER_USE", raising=False)
    loop = object.__new__(AgentLoop)
    loop._model = None  # type: ignore[attr-defined]
    await loop._resolve_vision_capable(None)
    assert loop._vision_capable is None
