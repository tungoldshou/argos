"""embedding 客户端测试 —— httpx monkeypatch,不连真网络。"""
import json
import pytest
from pathlib import Path

from argos import llm_embed


def test_embed_dim_is_1536():
    assert llm_embed.EMBED_DIM == 1536


def test_embed_text_hits_endpoint_and_returns_vectors(monkeypatch, tmp_path):
    captured = {}

    def fake_post(url, headers=None, json=None, timeout=None):
        captured["url"] = url
        captured["headers"] = headers
        captured["body"] = json
        class _R:
            status_code = 200
            def json(self): return {"vectors": [[0.1, 0.2, 0.3] * 512] * len(json["texts"])}
        return _R()

    monkeypatch.setattr(llm_embed.httpx, "post", fake_post)
    monkeypatch.setattr(llm_embed, "EMBED_URL", "http://test-emb/v1/embeddings")
    monkeypatch.setattr(llm_embed, "CACHE_PATH", tmp_path / "emb.json")  # 隔离:不读真磁盘缓存
    monkeypatch.setenv("VITE_MINIMAX_KEY", "k123")

    out = llm_embed.embed_text(["hello", "world"])
    assert len(out) == 2 and all(len(v) == 1536 for v in out)
    assert captured["url"] == "http://test-emb/v1/embeddings"
    assert captured["headers"]["Authorization"] == "Bearer k123"
    assert captured["body"] == {"model": "embo-01", "type": "db", "texts": ["hello", "world"]}


def test_embed_text_raises_embederror_on_http_failure(monkeypatch):
    class _R:
        status_code = 500
        text = "internal"
    monkeypatch.setattr(llm_embed.httpx, "post", lambda *a, **kw: _R())
    monkeypatch.setenv("VITE_MINIMAX_KEY", "k123")
    with pytest.raises(llm_embed.EmbedError):
        llm_embed.embed_text(["x"])


def test_embed_text_uses_disk_cache(tmp_path, monkeypatch):
    calls = {"n": 0}
    def fake_post(url, headers=None, json=None, timeout=None):
        calls["n"] += 1
        return type("R", (), {"status_code": 200, "json": lambda s: {"vectors": [[0.1] * 1536] * len(json["texts"])}})()
    monkeypatch.setattr(llm_embed.httpx, "post", fake_post)
    monkeypatch.setattr(llm_embed, "CACHE_PATH", tmp_path / "emb.json")
    monkeypatch.setenv("VITE_MINIMAX_KEY", "k123")

    a = llm_embed.embed_text(["hello"])
    b = llm_embed.embed_text(["hello"])  # 应走缓存
    assert calls["n"] == 1
    assert a == b


def test_embed_text_different_texts_different_cache_keys(tmp_path, monkeypatch):
    calls = {"n": 0}
    def fake_post(url, headers=None, json=None, timeout=None):
        calls["n"] += 1
        n = len(json["texts"])
        return type("R", (), {"status_code": 200, "json": lambda s: {"vectors": [[0.1] * 1536] * n}})()
    monkeypatch.setattr(llm_embed.httpx, "post", fake_post)
    monkeypatch.setattr(llm_embed, "CACHE_PATH", tmp_path / "emb.json")
    monkeypatch.setenv("VITE_MINIMAX_KEY", "k123")
    llm_embed.embed_text(["a"])
    llm_embed.embed_text(["b"])
    assert calls["n"] == 2
