"""Phase 2:embedding 抽象——source-agnostic(spec §5.4)。

锁死:① Embedder 协议形状(embed/dim);② EndpointEmbedder 包现 llm_embed;
③ get_embedder 在 MLX 构造失败时回退 endpoint;④ 全失败返回 None(让 recall 降级,不抛)。
"""
import pytest

from argos_agent.memory import embedding as emb


class _FakeEmbedder:
    dim = 4

    def embed(self, texts):
        return [[float(len(t)), 0.0, 0.0, 0.0] for t in texts]


def test_embedder_protocol_shape():
    e = _FakeEmbedder()
    out = e.embed(["ab", "cde"])
    assert out == [[2.0, 0.0, 0.0, 0.0], [3.0, 0.0, 0.0, 0.0]]
    assert e.dim == 4


def test_endpoint_embedder_wraps_llm_embed(monkeypatch):
    captured = {}

    def fake_embed_text(texts):
        captured["texts"] = texts
        return [[0.1] * 1536 for _ in texts]

    monkeypatch.setattr(emb, "_endpoint_embed_text", fake_embed_text)
    e = emb.EndpointEmbedder()
    out = e.embed(["x", "y"])
    assert captured["texts"] == ["x", "y"]
    assert len(out) == 2 and len(out[0]) == 1536
    assert e.dim == 1536


def test_get_embedder_falls_back_to_endpoint_when_mlx_unavailable(monkeypatch):
    # 强制 MLX 构造抛错 → 应回退 EndpointEmbedder
    def boom():
        raise RuntimeError("no mlx")

    monkeypatch.setattr(emb, "_build_mlx_embedder", boom)
    monkeypatch.setattr(emb, "_endpoint_embed_text", lambda texts: [[0.0] * 1536 for _ in texts])
    e = emb.get_embedder()
    assert isinstance(e, emb.EndpointEmbedder)


def test_get_embedder_returns_none_when_all_fail(monkeypatch):
    monkeypatch.setattr(emb, "_build_mlx_embedder", lambda: (_ for _ in ()).throw(RuntimeError("no mlx")))

    def endpoint_boom():
        raise RuntimeError("no endpoint")

    monkeypatch.setattr(emb, "_build_endpoint_embedder", endpoint_boom)
    assert emb.get_embedder() is None  # 全失败 → None,让 recall 走 FTS5 降级


def test_endpoint_embedder_propagates_embed_error_to_caller(monkeypatch):
    # 调用期失败(非构造期)应抛,让 store.recall 捕获后降级
    def fail(texts):
        raise emb.EmbedError("network down")

    monkeypatch.setattr(emb, "_endpoint_embed_text", fail)
    e = emb.EndpointEmbedder()
    with pytest.raises(emb.EmbedError):
        e.embed(["x"])
