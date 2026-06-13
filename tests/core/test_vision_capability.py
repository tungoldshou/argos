"""视觉能力检测:cache 持久 + probe 确定性 + resolve 级联(注入,不发真网络)。"""
from pathlib import Path
from argos.core.vision_capability import VisionCapabilityCache


def test_cache_set_get_roundtrip(tmp_path):
    c = VisionCapabilityCache(tmp_path / "vc.json")
    c.set("https://x/v1", "m", True)
    assert c.get("https://x/v1", "m") is True
    c.set("https://x/v1", "m2", False)
    assert c.get("https://x/v1", "m2") is False


def test_cache_unset_returns_none(tmp_path):
    c = VisionCapabilityCache(tmp_path / "vc.json")
    assert c.get("https://x/v1", "missing") is None


def test_cache_malformed_file_returns_none(tmp_path):
    p = tmp_path / "vc.json"
    p.write_text("not json{{{")
    c = VisionCapabilityCache(p)
    assert c.get("https://x/v1", "m") is None


def test_cache_isolated_by_base_url(tmp_path):
    c = VisionCapabilityCache(tmp_path / "vc.json")
    c.set("https://a/v1", "m", True)
    assert c.get("https://b/v1", "m") is None


import pytest
from argos.core.vision_capability import VisionProbe, _solid_png


class _FakeClient:
    def __init__(self, reply: str = "", raises: bool = False):
        self.reply = reply
        self.raises = raises
        self.last_messages = None

    async def complete(self, messages, *, system, **kw):
        self.last_messages = messages
        if self.raises:
            raise RuntimeError("network boom")
        return self.reply


def test_solid_png_is_valid_png():
    png = _solid_png((255, 0, 0))
    assert png[:8] == b"\x89PNG\r\n\x1a\n"


@pytest.mark.asyncio
async def test_probe_verified_when_model_names_color():
    client = _FakeClient(reply="The dominant color is Red.")
    assert await VisionProbe(color="red").run(client) is True
    assert client.last_messages[0]["attachments"], "probe 应发带 attachments 的消息"


@pytest.mark.asyncio
async def test_probe_false_when_model_cant_see():
    client = _FakeClient(reply="I don't see any image. Please provide one.")
    assert await VisionProbe(color="red").run(client) is False


@pytest.mark.asyncio
async def test_probe_false_on_wrong_color():
    client = _FakeClient(reply="blue")
    assert await VisionProbe(color="red").run(client) is False


@pytest.mark.asyncio
async def test_probe_false_on_client_error():
    client = _FakeClient(raises=True)
    assert await VisionProbe(color="green").run(client) is False


import types
from argos.core.vision_capability import resolve_vision_capability


class _FakeProbe:
    def __init__(self, result: bool):
        self.result = result
        self.calls = 0

    async def run(self, model_client) -> bool:
        self.calls += 1
        return self.result


def _tier(multimodal):
    return types.SimpleNamespace(multimodal=multimodal, base_url="https://x/v1", model="m")


@pytest.mark.asyncio
async def test_resolve_override_true_skips_probe(tmp_path):
    probe = _FakeProbe(False)
    cache = VisionCapabilityCache(tmp_path / "vc.json")
    ok = await resolve_vision_capability(_tier(True), None, cache, probe=probe)
    assert ok is True and probe.calls == 0


@pytest.mark.asyncio
async def test_resolve_override_false_skips_probe(tmp_path):
    probe = _FakeProbe(True)
    cache = VisionCapabilityCache(tmp_path / "vc.json")
    ok = await resolve_vision_capability(_tier(False), None, cache, probe=probe)
    assert ok is False and probe.calls == 0


@pytest.mark.asyncio
async def test_resolve_cache_hit_skips_probe(tmp_path):
    cache = VisionCapabilityCache(tmp_path / "vc.json")
    cache.set("https://x/v1", "m", True)
    probe = _FakeProbe(False)
    ok = await resolve_vision_capability(_tier(None), None, cache, probe=probe)
    assert ok is True and probe.calls == 0


@pytest.mark.asyncio
async def test_resolve_miss_probes_and_caches(tmp_path):
    cache = VisionCapabilityCache(tmp_path / "vc.json")
    probe = _FakeProbe(True)
    ok = await resolve_vision_capability(_tier(None), None, cache, probe=probe)
    assert ok is True and probe.calls == 1
    assert cache.get("https://x/v1", "m") is True
