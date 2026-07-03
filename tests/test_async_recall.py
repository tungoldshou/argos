"""Internal documentation."""
from __future__ import annotations

import asyncio

import pytest


# ── OpenAIEmbedder.aembed ──────────────────────────────────────────────────

class TestOpenAIEmbedderAembed:
    def _make_embedder(self, transport):
        from argos.memory.embedding import OpenAIEmbedder
        return OpenAIEmbedder(
            base_url="https://api.example.com/v1",
            api_key="test-key",
            model="text-embed-001",
            transport=transport,
        )

    @pytest.mark.asyncio
    async def test_aembed_returns_vectors(self):
        import json
        import httpx

        payload = {"data": [{"embedding": [0.1, 0.2, 0.3]}]}

        def handler(req: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json=payload)

        emb = self._make_embedder(httpx.MockTransport(handler))
        vecs = await emb.aembed(["hello world"])
        assert len(vecs) == 1
        assert vecs[0] == pytest.approx([0.1, 0.2, 0.3])
        assert emb.dim == 3

    @pytest.mark.asyncio
    async def test_aembed_raises_on_error(self):
        import httpx

        def handler(req: httpx.Request) -> httpx.Response:
            return httpx.Response(500, text="internal error")

        emb = self._make_embedder(httpx.MockTransport(handler))
        with pytest.raises(httpx.HTTPStatusError):
            await emb.aembed(["hello"])

    def test_sync_embed_uses_short_timeout(self, monkeypatch):
        """Internal documentation."""
        from argos.memory import embedding as emb_mod
        assert emb_mod._RECALL_ASYNC_TIMEOUT_S <= 10.0


# ── store.arecall ──────────────────────────────────────────────────────────

class TestStoreArecall:
    def _make_store(self, tmp_path, embedder=None):
        import os
        os.environ["ARGOS_DB_PATH"] = str(tmp_path / "test.db")
        from argos.memory.store import ArgosStore
        store = ArgosStore(db_path=str(tmp_path / "test.db"), embedder=embedder)
        return store

    @pytest.mark.asyncio
    async def test_arecall_empty_returns_empty(self, tmp_path):
        store = self._make_store(tmp_path)
        hits = await store.arecall("test goal")
        assert hits == []

    @pytest.mark.asyncio
    async def test_arecall_falls_back_to_fts5_when_no_embedder(self, tmp_path):
        """Internal documentation."""
        from argos.memory.store import ArgosStore
        store = ArgosStore(db_path=str(tmp_path / "test.db"), embedder=None)
        store._write(
            "INSERT INTO memory(id, goal, verdict, model, fact, ts) VALUES (?,?,?,?,?,?)",
            ("id1", "排序算法优化任务", "passed", "m1", None, 1.0),
        )
        hits = await store.arecall("排序算法")
        assert isinstance(hits, list)

    @pytest.mark.asyncio
    async def test_arecall_with_failing_aembed_falls_back_to_sync(self, tmp_path):
        """Internal documentation."""
        class FailingEmbedder:
            dim = 3
            def embed(self, texts):
                return [[0.0, 0.0, 0.0]] * len(texts)
            async def aembed(self, texts):
                raise RuntimeError("network down")

        from argos.memory.store import ArgosStore
        store = ArgosStore(db_path=str(tmp_path / "test.db"), embedder=FailingEmbedder())
        hits = await store.arecall("some goal")
        assert isinstance(hits, list)
