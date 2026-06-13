# Vision Capability Detection Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the static manual `multimodal` flag with lazy, cached, ground-truth vision probing — so a model's image capability is auto-discovered on first image use, verified against a known test image, cached per `(base_url, model)`, and honestly blocked when unverifiable.

**Architecture:** A new `core/vision_capability.py` provides `VisionProbe` (send a known random-color PNG, check the model names the color), `VisionCapabilityCache` (persistent `~/.argos/vision_cache.json`), and `resolve_vision_capability` (cascade: explicit `multimodal` override → cache → probe). `ModelTier.multimodal` becomes tri-state `bool | None` (None = unknown → probe). The loop's image gate (`loop.py:723`) calls `resolve_vision_capability` instead of reading a static bool.

**Tech Stack:** Python 3.12, stdlib only (`zlib`/`struct` for the probe PNG, `json` for the cache, `random`). Reuses the existing `ModelClient` + `protocols.payload` image path. No new pip deps. Tests: pytest.

**Spec:** `docs/superpowers/specs/2026-06-13-vision-capability-detection-design.md`.

---

## File Structure

- `argos/core/vision_capability.py` — **new.** Probe + cache + resolve cascade. One responsibility: answer "can this model see images?" empirically, cached. No TUI/daemon coupling.
- `argos/core/models.py` — `ModelTier.multimodal: bool` → `bool | None` (tri-state override).
- `argos/config.py` — read `multimodal` override from config.json into `ModelTier` (currently dropped at `config.py:189`).
- `argos/core/loop.py` — image gate (`:723`) calls `resolve_vision_capability` (async) instead of `not tier.multimodal`.
- Tests: `tests/core/test_vision_capability.py` (new), `tests/test_config_multimodal.py` (new), `tests/input/test_model_tier_multimodal.py` (update default), `tests/input/test_loop_multimodal.py` (update gate to async-resolve + add unknown/probe path).

---

## Task 1: `ModelTier.multimodal` → tri-state `bool | None`

**Files:**
- Modify: `argos/core/models.py` (the `multimodal` field, currently `bool = False`)
- Test: `tests/input/test_model_tier_multimodal.py`

- [ ] **Step 1: Update the failing test**

In `tests/input/test_model_tier_multimodal.py`, replace `test_model_tier_multimodal_defaults_false` with this (and keep the other two tests as-is):

```python
def test_model_tier_multimodal_defaults_none():
    """ModelTier 不传 multimodal → 默认 None(未知 → 走探针检测,不再默认 False)。"""
    tier = _make_tier()
    assert tier.multimodal is None


def test_model_tier_multimodal_explicit_false_is_override():
    """ModelTier(multimodal=False) → 显式 override 保留(用户声明纯文本)。"""
    tier = _make_tier(multimodal=False)
    assert tier.multimodal is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/input/test_model_tier_multimodal.py -o addopts="" -q`
Expected: FAIL — `test_model_tier_multimodal_defaults_none` asserts `None` but the field still defaults `False`.

- [ ] **Step 3: Change the field**

In `argos/core/models.py`, the `ModelTier` dataclass currently ends:

```python
    protocol: str = "anthropic"   # "anthropic" | "openai";默认值保旧构造点/旧 env 回退零破坏
    multimodal: bool = False       # 当前模型是否支持图像输入(spec §5);来自 config/setup 探针
```

Change the `multimodal` line to:

```python
    protocol: str = "anthropic"   # "anthropic" | "openai";默认值保旧构造点/旧 env 回退零破坏
    multimodal: bool | None = None  # 视觉能力 override:None=未知(走懒探针检测);True/False=用户显式声明(跳探针)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/input/test_model_tier_multimodal.py -o addopts="" -q`
Expected: PASS (3 passed — defaults_none, explicit_false, is_frozen)

- [ ] **Step 5: Commit**

```bash
git add argos/core/models.py tests/input/test_model_tier_multimodal.py
git commit -m "feat(models): ModelTier.multimodal tri-state (None=unknown→probe)"
```

---

## Task 2: `config.py` reads `multimodal` override

**Files:**
- Modify: `argos/config.py` (the `ModelTier(...)` build around `config.py:189`)
- Test: `tests/test_config_multimodal.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_config_multimodal.py`:

```python
"""config.json 的 multimodal override 三态读取:未设→None;true→True;false→False。"""
import json
from pathlib import Path
import pytest
from argos import config as C


def _write(tmp_path: Path, model_extra: dict) -> Path:
    cfg = {
        "active": "m",
        "models": {"m": {
            "model": "agnes-2.0-flash", "base_url": "https://x/v1",
            "protocol": "openai", "max_tokens": 1024, **model_extra,
        }},
    }
    (tmp_path / "config.json").write_text(json.dumps(cfg))
    return tmp_path


def _load_tier(tmp_path: Path):
    cfg = C.load_config(config_dir=tmp_path) if "config_dir" in C.load_config.__code__.co_varnames \
        else None
    # load_config 不接 config_dir 时,用 ARGOS_CONFIG_DIR 环境变量驱动
    return cfg


def test_multimodal_unset_is_none(tmp_path, monkeypatch):
    monkeypatch.setenv("ARGOS_CONFIG_DIR", str(_write(tmp_path, {})))
    cfg = C.load_config()
    assert cfg.tiers["m"].multimodal is None


def test_multimodal_true_override(tmp_path, monkeypatch):
    monkeypatch.setenv("ARGOS_CONFIG_DIR", str(_write(tmp_path, {"multimodal": True})))
    cfg = C.load_config()
    assert cfg.tiers["m"].multimodal is True


def test_multimodal_false_override(tmp_path, monkeypatch):
    monkeypatch.setenv("ARGOS_CONFIG_DIR", str(_write(tmp_path, {"multimodal": False})))
    cfg = C.load_config()
    assert cfg.tiers["m"].multimodal is False
```

(Executor note: `load_config()` resolves the config dir from `ARGOS_CONFIG_DIR` — confirm by reading `argos/config.py`'s `_config_dir`/`load_config`; if it takes a `config_dir=` kwarg instead, simplify the test to pass it directly. The behavior asserted is the same: `multimodal` reads three-state from the profile dict.)

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_config_multimodal.py -o addopts="" -q`
Expected: FAIL — `test_multimodal_true_override` gets `None` (config.py drops `multimodal` today).

- [ ] **Step 3: Read `multimodal` in the build**

In `argos/config.py`, the `ModelTier(...)` build currently is:

```python
        tiers[name] = ModelTier(
            name=name, model=m["model"], base_url=m["base_url"],
            max_tokens=max_tokens, context_window=context_window, protocol=m["protocol"],
        )
```

Add the `multimodal` override read:

```python
        tiers[name] = ModelTier(
            name=name, model=m["model"], base_url=m["base_url"],
            max_tokens=max_tokens, context_window=context_window, protocol=m["protocol"],
            multimodal=m.get("multimodal"),   # 未设→None(走探针);true/false→显式 override
        )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_config_multimodal.py -o addopts="" -q`
Expected: PASS (3 passed)

- [ ] **Step 5: Commit**

```bash
git add argos/config.py tests/test_config_multimodal.py
git commit -m "feat(config): read multimodal override from config.json (tri-state)"
```

---

## Task 3: `VisionCapabilityCache` + module skeleton

**Files:**
- Create: `argos/core/vision_capability.py`
- Test: `tests/core/test_vision_capability.py`

- [ ] **Step 1: Write the failing test**

Create `tests/core/test_vision_capability.py`:

```python
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
    assert c.get("https://x/v1", "m") is None  # 畸形 → 空缓存,不崩


def test_cache_isolated_by_base_url(tmp_path):
    c = VisionCapabilityCache(tmp_path / "vc.json")
    c.set("https://a/v1", "m", True)
    assert c.get("https://b/v1", "m") is None  # 不同 base_url 不串
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/core/test_vision_capability.py -o addopts="" -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'argos.core.vision_capability'`

- [ ] **Step 3: Create the module with the cache**

Create `argos/core/vision_capability.py`:

```python
"""视觉能力检测:懒触发探针 + 缓存(spec 2026-06-13)。

不提前声明能力;第一次给某 (base_url, model) 发图时,用一张已知答案的图探一次,缓存。
verify-gate 灵魂在视觉上的复刻:别信声明,验它。
本模块宿主侧跑(复用 ModelClient),无 TUI/daemon 耦合。
"""
from __future__ import annotations

import json
import time
from pathlib import Path


class VisionCapabilityCache:
    """(base_url, model) → 是否支持视觉,持久缓存(默认 ~/.argos/vision_cache.json)。
    机器探测结果,与用户声明(config.json)分开。"""

    def __init__(self, path: Path | None = None) -> None:
        if path is None:
            import os
            cdir = Path(os.environ.get("ARGOS_CONFIG_DIR") or (Path.home() / ".argos"))
            path = cdir / "vision_cache.json"
        self._path = path

    def _load(self) -> dict:
        try:
            return json.loads(self._path.read_text()) or {}
        except Exception:  # noqa: BLE001 — 缺文件/畸形 json → 空缓存
            return {}

    def get(self, base_url: str, model: str) -> bool | None:
        """未缓存 → None;命中 → bool。"""
        entry = (self._load().get(base_url) or {}).get(model)
        if isinstance(entry, dict) and isinstance(entry.get("verified"), bool):
            return entry["verified"]
        return None

    def set(self, base_url: str, model: str, verified: bool) -> None:
        data = self._load()
        data.setdefault(base_url, {})[model] = {"verified": verified, "ts": time.time()}
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            self._path.write_text(json.dumps(data, indent=2, ensure_ascii=False))
        except Exception:  # noqa: BLE001 — 写失败不致命(下次重探)
            pass
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/core/test_vision_capability.py -o addopts="" -q`
Expected: PASS (4 passed)

- [ ] **Step 5: Commit**

```bash
git add argos/core/vision_capability.py tests/core/test_vision_capability.py
git commit -m "feat(vision): VisionCapabilityCache (persistent per base_url+model)"
```

---

## Task 4: `VisionProbe` (known-image ground-truth probe)

**Files:**
- Modify: `argos/core/vision_capability.py` (append colors + `_solid_png` + `VisionProbe`)
- Test: `tests/core/test_vision_capability.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/core/test_vision_capability.py`:

```python
import pytest
from argos.core.vision_capability import VisionProbe, _solid_png


class _FakeClient:
    """冒充 ModelClient:记录收到的 messages,按脚本回 reply / 抛错。"""
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
    # 确实发了带图片附件的消息(真走附件路径)
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
    assert await VisionProbe(color="green").run(client) is False  # 网络错 → 不可验 → False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/core/test_vision_capability.py -k "probe or solid_png" -o addopts="" -q`
Expected: FAIL — `ImportError: cannot import name 'VisionProbe'`

- [ ] **Step 3: Append colors + `_solid_png` + `VisionProbe`**

Append to `argos/core/vision_capability.py`:

```python
import random
import struct
import zlib

# 6 个名字稳定的明显色;探针随机选一个,盲模型 1/6 蒙不中。
_PROBE_COLORS: dict[str, tuple[int, int, int]] = {
    "red": (255, 0, 0), "green": (0, 200, 0), "blue": (0, 0, 255),
    "yellow": (255, 255, 0), "black": (0, 0, 0), "white": (255, 255, 255),
}
# 小同义集(模型可能用别名;v1 仅 grey/gray 一例,其余同名)。
_COLOR_SYNONYMS: dict[str, tuple[str, ...]] = {
    "red": ("red",), "green": ("green",), "blue": ("blue",),
    "yellow": ("yellow",), "black": ("black",), "white": ("white",),
}


def _solid_png(rgb: tuple[int, int, int], w: int = 16, h: int = 16) -> bytes:
    """生成 w×h 纯色 PNG(stdlib,无 PIL)。"""
    def chunk(typ: bytes, data: bytes) -> bytes:
        c = typ + data
        return struct.pack(">I", len(data)) + c + struct.pack(">I", zlib.crc32(c) & 0xFFFFFFFF)
    raw = (b"\x00" + bytes(rgb) * w) * h          # 每行:filter 0 + w 个 RGB 像素
    return (b"\x89PNG\r\n\x1a\n"
            + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw))
            + chunk(b"IEND", b""))


class VisionProbe:
    """给 model_client 发一张已知色块图,核对它能否说出该色 → 是否真支持视觉。
    确定性 ground truth;任何异常(网络/API/400)→ False(不可验即不支持,绝不假设 yes)。"""

    def __init__(self, *, color: str | None = None) -> None:
        self._color = color  # None=随机;注入固定色做测试确定性

    async def run(self, model_client) -> bool:
        from argos.input.attachments import ImageAttachment
        color = self._color or random.choice(list(_PROBE_COLORS))
        png = _solid_png(_PROBE_COLORS[color])
        att = ImageAttachment(data=png, media_type="image/png", source_label="vision-probe")
        msgs = [{
            "role": "user",
            "content": "What is the single dominant color of this image? Reply with ONLY the color word.",
            "attachments": [att],
        }]
        try:
            resp = await model_client.complete(msgs, system="You are a vision capability test.")
        except Exception:  # noqa: BLE001 — 网络/API/400 等 → 不可验 → 不支持
            return False
        low = (resp or "").lower()
        return any(syn in low for syn in _COLOR_SYNONYMS[color])
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/core/test_vision_capability.py -k "probe or solid_png" -o addopts="" -q`
Expected: PASS (5 passed)

- [ ] **Step 5: Commit**

```bash
git add argos/core/vision_capability.py tests/core/test_vision_capability.py
git commit -m "feat(vision): VisionProbe (known random-color image, ground-truth check)"
```

---

## Task 5: `resolve_vision_capability` cascade

**Files:**
- Modify: `argos/core/vision_capability.py` (append `resolve_vision_capability`)
- Test: `tests/core/test_vision_capability.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/core/test_vision_capability.py`:

```python
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
    assert ok is True and probe.calls == 0  # override 短路,不探


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
    assert ok is True and probe.calls == 0  # 缓存命中,不探


@pytest.mark.asyncio
async def test_resolve_miss_probes_and_caches(tmp_path):
    cache = VisionCapabilityCache(tmp_path / "vc.json")
    probe = _FakeProbe(True)
    ok = await resolve_vision_capability(_tier(None), None, cache, probe=probe)
    assert ok is True and probe.calls == 1          # 未知 → 探一次
    assert cache.get("https://x/v1", "m") is True    # 结果写入缓存
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/core/test_vision_capability.py -k resolve -o addopts="" -q`
Expected: FAIL — `ImportError: cannot import name 'resolve_vision_capability'`

- [ ] **Step 3: Append the cascade**

Append to `argos/core/vision_capability.py`:

```python
async def resolve_vision_capability(tier, model_client, cache, *, probe=None) -> bool:
    """级联判定模型能否看图:
    ① tier.multimodal 非 None → 用 override(跳探针);
    ② 缓存命中 (base_url, model) → 用缓存;
    ③ 否则 → 探针 → 写缓存 → 返回。
    probe 可注入(测试不发真网络)。"""
    override = getattr(tier, "multimodal", None)
    if override is not None:
        return bool(override)
    cached = cache.get(tier.base_url, tier.model)
    if cached is not None:
        return cached
    verified = await (probe or VisionProbe()).run(model_client)
    cache.set(tier.base_url, tier.model, verified)
    return verified
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/core/test_vision_capability.py -o addopts="" -q`
Expected: PASS (all vision_capability tests, ~13 passed)

- [ ] **Step 5: Commit**

```bash
git add argos/core/vision_capability.py tests/core/test_vision_capability.py
git commit -m "feat(vision): resolve_vision_capability cascade (override→cache→probe)"
```

---

## Task 6: wire the loop gate to `resolve_vision_capability`

**Files:**
- Modify: `argos/core/loop.py` (the image gate at `loop.py:723-731`)
- Test: `tests/input/test_loop_multimodal.py`

- [ ] **Step 1: Update / extend the test**

In `tests/input/test_loop_multimodal.py`, add an unknown-tier helper next to `_plain_tier`/`_mm_tier`:

```python
def _unknown_tier():
    """未知能力(multimodal=None)→ 门走 resolve 探针。"""
    from argos.core.models import ModelTier
    return ModelTier(name="default", model="agnes-flash", base_url="https://x",
                     max_tokens=64, multimodal=None)
```

Then append these two tests (the existing `test_plain_tier_with_attachments_raises_honest_error` still passes — explicit `multimodal=False` is now an override that `resolve` returns False for, and the new error message still contains "multimodal"):

```python
@pytest.mark.asyncio
async def test_unknown_tier_blocks_when_resolve_false(monkeypatch):
    """multimodal=None(未知)+ 附件:门走 resolve;resolve→False → 诚实阻断。"""
    import argos.core.vision_capability as vc

    async def _fake_resolve(tier, model_client, cache, **kw):
        return False
    monkeypatch.setattr(vc, "resolve_vision_capability", _fake_resolve)

    loop = _make_minimal_loop(_unknown_tier())
    events = []
    try:
        async for ev in loop.run("x", "s", attachments=[_att()]):
            events.append(ev)
    except Exception as e:
        assert "看不了图" in str(e) or "multimodal" in str(e).lower()
        return
    from argos.protocol.events import Error
    assert any(isinstance(ev, Error) for ev in events), "resolve→False 应诚实阻断"


@pytest.mark.asyncio
async def test_unknown_tier_passes_gate_when_resolve_true(monkeypatch):
    """resolve→True → 门放行(后续可能因 mock 不全出别的错,但不是视觉门)。"""
    import argos.core.vision_capability as vc

    async def _fake_resolve(tier, model_client, cache, **kw):
        return True
    monkeypatch.setattr(vc, "resolve_vision_capability", _fake_resolve)

    loop = _make_minimal_loop(_unknown_tier())
    try:
        async for _ev in loop.run("x", "s", attachments=[_att()]):
            pass
    except Exception as e:  # noqa: BLE001
        assert "看不了图" not in str(e) and "multimodal" not in str(e).lower(), (
            f"resolve→True 不应触发视觉门,但得到: {e}"
        )
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/input/test_loop_multimodal.py -o addopts="" -q`
Expected: FAIL — `test_unknown_tier_blocks_when_resolve_false` fails: with `multimodal=None` the current gate `not getattr(tier, "multimodal", False)` → `not None` → True → raises with the OLD message (no "看不了图"), and it never calls `resolve_vision_capability` (so the monkeypatch is irrelevant). The assertion `"看不了图" in str(e)` fails.

- [ ] **Step 3: Rewrite the gate to use `resolve_vision_capability`**

In `argos/core/loop.py`, the gate currently is:

```python
        # 多模态门禁(spec §5 诚实不变量):发请求前若存在附件但 tier.multimodal=False
        # → 抛诚实错误,不静默剥图,不假装看到。
        if attachments:
            tier = getattr(getattr(self, "_model", None), "tier", None)
            if tier is not None and not getattr(tier, "multimodal", False):
                model_name = getattr(tier, "model", "当前模型")
                raise ValueError(
                    f"当前模型 {model_name!r} 不支持图像输入（multimodal=False）。"
                    "请在 setup 配置一个多模态模型（如 claude-3-5-sonnet / gpt-4o）。"
                )
```

Replace it with:

```python
        # 视觉能力门(spec 2026-06-13):发请求前判定模型能否看图。能力靠"懒触发探针 + 缓存"
        # 自发现(override→缓存→探针),探不出/看不了 → 诚实阻断,不静默剥图、不假装看到。
        if attachments:
            tier = getattr(getattr(self, "_model", None), "tier", None)
            if tier is not None:
                from argos.core.vision_capability import (
                    resolve_vision_capability, VisionCapabilityCache,
                )
                ok = await resolve_vision_capability(tier, self._model, VisionCapabilityCache())
                if not ok:
                    model_name = getattr(tier, "model", "当前模型")
                    raise ValueError(
                        f"当前模型 {model_name!r} 看不了图。请换一个支持视觉的模型,"
                        "或在 config 给该 profile 设 multimodal override。"
                    )
```

(The gate stays before `self._reset_run_state()` and before the top-level `try`, same as today. The raise propagates out of `run()`; the inline TUI `_produce` wrapper and the daemon worker `try/except → mark_failed` both convert it to an honest Error — verified earlier, no gate-move needed.)

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/input/test_loop_multimodal.py -o addopts="" -q`
Expected: PASS (all — the 2 new tests + the existing override/no-attachment tests)

- [ ] **Step 5: Run the broader loop + attachments suites for regression**

Run: `uv run pytest tests/test_loop.py tests/test_loop_attachments.py tests/input/ -o addopts="" -q`
Expected: PASS (the gate is now async-resolve but override + no-attachment paths are unchanged; image-bearing tests that relied on `multimodal=True` still pass via the override short-circuit)

- [ ] **Step 6: Commit**

```bash
git add argos/core/loop.py tests/input/test_loop_multimodal.py
git commit -m "feat(loop): image gate uses resolve_vision_capability (probe+cache, not static flag)"
```

---

## Task 7: full-suite verification gate

**Files:** none (verification only)

- [ ] **Step 1: Run the full suite with coverage**

Run: `uv run pytest -n auto --dist loadgroup -q`
Expected: green except the known pre-existing/environmental failures (tiktoken-venv ×7, docker ×1, `@binary-dist`, timing/xdist-race). Coverage ≥ 80%. If coverage prints a glitched low number under xdist, re-read it with `uv run coverage report --format=total` (combined data).

- [ ] **Step 2: Confirm no NEW failures**

Compare the failure list against the known-environmental set. Any failure in `vision_capability` / `loop` / `config` / `models` / `multimodal` test files is a real regression — fix before proceeding. (Watch especially for other tests that constructed `ModelTier` expecting `multimodal` to default `False`; grep `git grep -n "multimodal" tests/` and fix any `is False` default-assumption.)

- [ ] **Step 3: Real-probe smoke (manual, honest — not automated)**

With a multimodal model configured (e.g. `agnes-2.0-flash`) and `multimodal` UNSET in config.json:
```bash
rm -f ~/.argos/vision_cache.json   # force a fresh probe
# attach an image in the TUI and submit
```
Expected: first image use triggers one probe call → if the model names the color, image goes through + `~/.argos/vision_cache.json` gains `{base_url: {model: {verified: true}}}`; second image use skips the probe. A text-only model → honest block. This is the unverifiable-on-CI path (no automation).

- [ ] **Step 4: No commit** (verification only).

---

## Self-Review

**Spec coverage (against `2026-06-13-vision-capability-detection-design.md`):**
- §2.1 lazy probe + cache on first image → Tasks 4, 5, 6. ✅
- §2.2 random-color known-image probe, color injectable → Task 4. ✅
- §2.3 fail = honest hard-block → Task 6 (raise). ✅ (§11 criterion 3)
- §2.4 `multimodal: bool | None` tri-state (unknown≠False) → Task 1. ✅
- §2.5 separate `vision_cache.json` keyed by (base_url, model) → Task 3. ✅ (§11 criterion 5)
- §4.1/4.2/4.3 VisionProbe / Cache / resolve cascade → Tasks 4, 3, 5. ✅
- §5 config reads override → Task 2. ✅ (§11 criterion 1)
- §6 gate uses resolve (async) → Task 6. ✅
- §7 probe network-fail → False → Task 4 (`test_probe_false_on_client_error`). ✅ (§11 criterion 4)
- §11 criterion 6 (no attachments → no probe/cache) → the gate is inside `if attachments:`; resolve never called otherwise. ✅
- §11 criterion 2 (first image probes+caches, second skips) → Task 5 (`test_resolve_miss_probes_and_caches` + `test_resolve_cache_hit_skips_probe`); end-to-end is the Task 7 manual smoke (unverifiable on CI). ✅

**Out of scope (spec §9, intentionally):** models.dev registry fast-path, setup-wizard proactive probe, Hermes-style transcribe-degrade. Not in any task — correct.

**Placeholder scan:** No TBD/TODO; every code step shows complete code. The Task 2 executor-note about `load_config`'s config-dir mechanism is a verification instruction (the asserted behavior is fixed), not a placeholder. ✅

**Type consistency:** `VisionProbe(*, color=None).run(model_client) -> bool`, `VisionCapabilityCache(path=None).get/set`, `resolve_vision_capability(tier, model_client, cache, *, probe=None) -> bool` — defined in Tasks 3/4/5 and used identically in Task 6's gate. `ModelTier.multimodal: bool | None` (Task 1) read as override in `config.py` (Task 2) and short-circuited in resolve (Task 5). `_FakeProbe.run`/`_FakeClient.complete` signatures match the real interfaces they stand in for. ✅

---

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-06-13-vision-capability-detection.md`. Two execution options:

1. **Subagent-Driven (recommended)** — fresh subagent per task, two-stage review between tasks.
2. **Inline Execution** — execute tasks in this session via executing-plans, batch with checkpoints.

Which approach?
