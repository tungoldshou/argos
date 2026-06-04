"""MiniMax `embo-01` 嵌入客户端 + 本地缓存。

URL/协议/响应 shape 全部由 Task 1 探针确认:
  - URL https://api.minimaxi.com/v1/embeddings(走主域,**不**走 /anthropic 路径)
  - Auth: Authorization: Bearer <KEY>(OpenAI-style)
  - Body: {"model": "embo-01", "type": "db", "texts": [...]}
  - Response: {"vectors": [[...1536 floats...]], "base_resp": {...}}
  - EMBED_DIM = 1536
失败 → 抛 EmbedError,让上层(记忆召回 ArgosStore)决定降级到「FTS5 关键词召回」,不崩主进程。
"""
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
EMBED_TYPE = "db"  # 「库」侧:技能/记忆都视同被索引的"文档"
CACHE_PATH = Path(os.environ.get("ARGOS_EMB_CACHE", Path.home() / ".argos" / "embeddings.json"))


class EmbedError(RuntimeError):
    """嵌入调用失败(网络/非200/JSON 坏)。上层必须降级,绝不掀翻 run。"""


def _cache_key(text: str) -> str:
    return hashlib.sha1(f"{EMBED_MODEL}:{EMBED_TYPE}:{text}".encode("utf-8")).hexdigest()[:16]


def _load_cache() -> dict[str, list[float]]:
    if not CACHE_PATH.exists():
        return {}
    try:
        return json.loads(CACHE_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}  # 坏文件当空,别因为本地 cache 把 sidecar 炸了


def _save_cache(cache: dict[str, list[float]]) -> None:
    try:
        CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
        tmp = CACHE_PATH.with_suffix(".tmp")
        tmp.write_text(json.dumps(cache), encoding="utf-8")
        tmp.replace(CACHE_PATH)  # 原子 rename
    except Exception:
        pass  # 写不进去下次重算,本机能写就下次再写


def embed_text(texts: list[str]) -> list[list[float]]:
    """调嵌入;命中本地缓存直接返,未命中批量补;任何失败 → EmbedError。"""
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
    # type: ignore[list-item] — out 已填满
    return out  # type: ignore[return-value]
