"""Internal documentation."""
from __future__ import annotations

from typing import Protocol, runtime_checkable

from argos.llm_embed import embed_text as _llm_embed_text, EmbedError, EMBED_DIM

_endpoint_embed_text = _llm_embed_text

_RECALL_ASYNC_TIMEOUT_S: float = 5.0


@runtime_checkable
class Embedder(Protocol):
    """Internal documentation."""
    dim: int

    def embed(self, texts: list[str]) -> list[list[float]]: ...


class EndpointEmbedder:
    """Internal documentation."""

    def __init__(self) -> None:
        self.dim = EMBED_DIM

    def embed(self, texts: list[str]) -> list[list[float]]:
        return _endpoint_embed_text(texts)


class OpenAIEmbedder:
    """Internal documentation."""

    def __init__(self, *, base_url: str, api_key: str, model: str, transport=None) -> None:
        self._base = base_url.rstrip("/")
        self._key = api_key
        self._model = model
        self._transport = transport
        self.dim = 0

    def _endpoint(self) -> str:
        return self._base if self._base.endswith("/embeddings") else self._base + "/embeddings"

    def embed(self, texts: list[str]) -> list[list[float]]:
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
        """Internal documentation."""
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
    """Internal documentation."""
    return EndpointEmbedder()


def get_embedder() -> Embedder | None:
    """Internal documentation."""
    try:
        return _build_endpoint_embedder()
    except Exception:
        return None
