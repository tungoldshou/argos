from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any

import httpx

EMBED_DIM = 1536
EMBED_URL = "https://api.minimaxi.com/v1/embeddings"
EMBED_MODEL = "embo-01"
EMBED_TYPE = "db"
CACHE_PATH: Path | None = None


class EmbedError(RuntimeError):
    pass


def _cache_key(text: str) -> str:
    return hashlib.sha1(f"{EMBED_MODEL}:{EMBED_TYPE}:{text}".encode("utf-8")).hexdigest()[:16]


def _cache_path() -> Path:
    if CACHE_PATH is not None:
        return CACHE_PATH
    if override := os.environ.get("ARGOS_EMB_CACHE"):
        return Path(override).expanduser()
    from argos import config
    return config.config_dir() / "embeddings.json"


def _load_cache() -> dict[str, list[float]]:
    path = _cache_path()
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save_cache(cache: dict[str, list[float]]) -> None:
    try:
        path = _cache_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(cache), encoding="utf-8")
        tmp.replace(path)
    except Exception:
        pass


def embed_text(texts: list[str]) -> list[list[float]]:
    key = os.environ.get("VITE_LLM_KEY") or os.environ.get("VITE_MINIMAX_KEY") or os.environ.get("MINIMAX_KEY")
    if not key:
        raise EmbedError("no LLM key configured")
    cache = _load_cache()
    out: list[list[float] | None] = [None] * len(texts)  # type: ignore[list-item]
    pending_idx: list[int] = []
    pending_texts: list[str] = []
    for i, t in enumerate(texts):
        k = _cache_key(t)
        if k in cache and len(cache[k]) == EMBED_DIM:
            out[i] = cache[k]
        else:
            pending_idx.append(i)
            pending_texts.append(t)
    if pending_texts:
        try:
            r = httpx.post(
                EMBED_URL,
                headers={"Content-Type": "application/json", "Authorization": f"Bearer {key}"},
                json={"model": EMBED_MODEL, "type": EMBED_TYPE, "texts": pending_texts},
                timeout=20.0,
            )
        except Exception as e:
            raise EmbedError(f"network: {e!r}") from e
        if r.status_code != 200:
            raise EmbedError(f"http {r.status_code}: {r.text[:200]}")
        try:
            data = r.json()
            vecs = data.get("vectors")
        except Exception as e:
            raise EmbedError(f"bad json: {e!r}") from e
        if not isinstance(vecs, list) or len(vecs) != len(pending_texts):
            raise EmbedError(f"shape mismatch: got {type(vecs).__name__}, expected list of {len(pending_texts)}")
        for j, pi in enumerate(pending_idx):
            v = vecs[j]
            if not isinstance(v, list) or len(v) != EMBED_DIM:
                raise EmbedError(f"dim mismatch: got {len(v) if isinstance(v, list) else type(v).__name__}")
            out[pi] = v
            cache[_cache_key(pending_texts[j])] = v
        _save_cache(cache)
    # type: ignore[list-item]
    return out  # type: ignore[return-value]
