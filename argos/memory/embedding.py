"""source-agnostic embedding 抽象(spec §5.4)。

生产装配走 config.active_embedder()(OpenAIEmbedder / None)。get_embedder() 是历史 fallback
装配路径(EndpointEmbedder = MiniMax embo-01 → None);失败返回 None,让 recall 走 FTS5 字面
降级(诚实:embedding 不可用就老实说,不假装搜过)。

store 持有 Embedder | None,绝不直接 import 具体后端——换后端零改动。

#4 async 召回:OpenAIEmbedder 提供 aembed(texts) 异步方法(httpx.AsyncClient),
供 store.arecall(goal) 在事件循环上非阻塞地召回 —— 避免 httpx.Client(timeout=30)
在主 async 事件循环上阻塞 30s。降级:aembed 失败 → store.arecall 退 FTS5(与同步路径一致)。
"""
from __future__ import annotations

from typing import Protocol, runtime_checkable

# 复用现有端点客户端(MiniMax embo-01,EMBED_DIM=1536)及其异常
from argos.llm_embed import embed_text as _llm_embed_text, EmbedError, EMBED_DIM

# 模块级间接层,便于测试 monkeypatch
_endpoint_embed_text = _llm_embed_text

# #4:recall 超时降级窗口。慢嵌入器超过此值 → FTS5 降级,而非冻结主循环 30s。
_RECALL_ASYNC_TIMEOUT_S: float = 5.0


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
        # #4:同步路径超时由 _RECALL_ASYNC_TIMEOUT_S 控制(比旧的 30s 短,
        # 让慢嵌入器更快降级 FTS5 而非冻结线程)。
        import httpx
        with httpx.Client(transport=self._transport, timeout=_RECALL_ASYNC_TIMEOUT_S) as client:
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

    async def aembed(self, texts: list[str]) -> list[list[float]]:
        """#4 异步 embed:httpx.AsyncClient + _RECALL_ASYNC_TIMEOUT_S 超时,不阻塞事件循环。

        超时由 httpx.AsyncClient(timeout=...) 控制(httpx 内部用 asyncio.CancelledError 实现),
        无需外层再包 asyncio.wait_for —— 避免双重超时竞争。
        失败(网络/超时/非 2xx) → 抛异常,调用方(store.arecall)捕获后降级 FTS5,
        绝不让嵌入失败掀翻整个 run。
        """
        import httpx
        async with httpx.AsyncClient(
            transport=self._transport, timeout=_RECALL_ASYNC_TIMEOUT_S,
        ) as client:
            resp = await client.post(
                self._endpoint(),
                headers={"Authorization": f"Bearer {self._key}",
                         "content-type": "application/json"},
                json={"model": self._model, "input": texts},
            )
            resp.raise_for_status()
            data = resp.json().get("data") or []
        vecs = [(row.get("embedding") or []) for row in data]
        if vecs and vecs[0]:
            self.dim = len(vecs[0])
        return vecs


def _build_endpoint_embedder() -> Embedder:
    """构造 EndpointEmbedder(可被测试 monkeypatch 成抛错)。"""
    return EndpointEmbedder()


def get_embedder() -> Embedder | None:
    """历史 fallback 装配路径:EndpointEmbedder(MiniMax embo-01),失败返回 None(让 recall
    降级到 FTS5)。生产主路径是 config.active_embedder()(OpenAIEmbedder / None)。

    构造期失败才回退 None;调用期失败(embed 抛 EmbedError)由 store.recall 自行降级。
    """
    try:
        return _build_endpoint_embedder()
    except Exception:
        return None
