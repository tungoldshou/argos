"""source-agnostic embedding 抽象(spec §5.4)。

默认本地 MLX(Jina v5-small 多语言,on-device/快/不出网,首次懒下载 ~600MB);
失败回退现 llm_embed 远程端点;再失败返回 None,让 recall 走 FTS5 字面降级
(诚实:embedding 不可用就老实说,不假装搜过)。

store 持有 Embedder | None,绝不直接 import 具体后端——换后端零改动。
"""
from __future__ import annotations

import os
from typing import Protocol, runtime_checkable

# 复用现有端点客户端(MiniMax embo-01,EMBED_DIM=1536)及其异常
from argos_agent.llm_embed import embed_text as _llm_embed_text, EmbedError, EMBED_DIM

# 模块级间接层,便于测试 monkeypatch
_endpoint_embed_text = _llm_embed_text

# Delta 锁#7:默认多语言 Jina v5-small(非 v2-small-en,不支持 CJK)。
# jinaai/jina-embeddings-v3 是 Jina v3 多语言官方模型;Phase 6 集成时确认 MLX 可加载的确切 id。
# TODO(Phase 6): confirm exact MLX-loadable id for this model during real-download integration
MLX_MODEL = os.environ.get("ARGOS_EMBED_MODEL", "jinaai/jina-embeddings-v3")


@runtime_checkable
class Embedder(Protocol):
    """文本 → 向量。dim = 向量维度(建 sqlite-vec 表时需要)。"""
    dim: int

    def embed(self, texts: list[str]) -> list[list[float]]: ...


class EndpointEmbedder:
    """包现 llm_embed 远程端点(MiniMax embo-01,1536 维)。"""

    def __init__(self) -> None:
        self.dim = EMBED_DIM

    def embed(self, texts: list[str]) -> list[list[float]]:
        # 调用期失败抛 EmbedError,让 store.recall 捕获后降级(不在这里吞)
        return _endpoint_embed_text(texts)


class MLXEmbedder:
    """本地 MLX embedding(懒下载权重)。构造期下载/加载模型,失败抛 → get_embedder 回退。"""

    def __init__(self, model: str = MLX_MODEL) -> None:
        from mlx_embeddings.utils import load  # 懒 import,缺包/缺权重在此抛

        self._model, self._tokenizer = load(model)
        # 探测维度:embed 一个探针取长度
        probe = self._embed_raw(["probe"])
        self.dim = len(probe[0])

    def _embed_raw(self, texts: list[str]) -> list[list[float]]:
        import mlx.core as mx  # noqa: F401

        out = self._model.encode(texts, tokenizer=self._tokenizer)
        # mlx 返回 mx.array;转 python list
        return [list(map(float, row)) for row in out.tolist()]

    def embed(self, texts: list[str]) -> list[list[float]]:
        return self._embed_raw(texts)


class OpenAIEmbedder:
    """复用 active profile 的 OpenAI 兼容 provider 做向量召回:打 <base_url>/embeddings(Bearer)。
    chat 模型 ≠ embedding 模型,故需单独的 embedding 模型名;上层(config.active_embedder)在未配
    embedding 模型 / 非 openai 协议时返 None → 记忆诚实走 FTS5,绝不偷调模型。
    构造不联网;dim 惰性(首次 embed 后置);首次 embed 失败由 store.recall 捕获降级 FTS5。"""

    def __init__(self, *, base_url: str, api_key: str, model: str, transport=None) -> None:
        self._base = base_url.rstrip("/")
        self._key = api_key
        self._model = model
        self._transport = transport   # 测试注入 httpx.MockTransport
        self.dim = 0                   # 惰性:首次 embed 后置真实维度

    def _endpoint(self) -> str:
        # base_url 约定含到 /v1;幂等拼 /embeddings(防已含后缀双拼)。
        return self._base if self._base.endswith("/embeddings") else self._base + "/embeddings"

    def embed(self, texts: list[str]) -> list[list[float]]:
        import httpx
        with httpx.Client(transport=self._transport, timeout=30.0) as client:
            resp = client.post(
                self._endpoint(),
                headers={"Authorization": f"Bearer {self._key}", "content-type": "application/json"},
                json={"model": self._model, "input": texts},
            )
            resp.raise_for_status()
            data = resp.json().get("data") or []
        vecs = [(row.get("embedding") or []) for row in data]
        if vecs and vecs[0]:
            self.dim = len(vecs[0])
        return vecs


def _build_mlx_embedder() -> Embedder:
    """构造 MLXEmbedder(可被测试 monkeypatch 成抛错)。"""
    return MLXEmbedder()


def _build_endpoint_embedder() -> Embedder:
    """构造 EndpointEmbedder(可被测试 monkeypatch 成抛错)。"""
    return EndpointEmbedder()


def get_embedder() -> Embedder | None:
    """默认 MLX,失败回退 endpoint,再失败返回 None(让 recall 降级到 FTS5)。

    构造期失败才回退;调用期失败(embed 抛 EmbedError)由 store.recall 自行降级。
    """
    try:
        return _build_mlx_embedder()
    except Exception:
        pass
    try:
        return _build_endpoint_embedder()
    except Exception:
        return None
