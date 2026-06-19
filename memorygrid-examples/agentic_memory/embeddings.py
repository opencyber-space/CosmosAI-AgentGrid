import hashlib
import random
from typing import Callable, List, Optional


class EmbeddingProvider:
    """
    Embedding provider backed by the OpenAI embeddings API.

    Pass embed_fn to override embedding entirely with a custom callable (useful
    in unit tests that patch this class out):
        provider = EmbeddingProvider(embed_fn=my_fn, dim=1536)

    Requires: pip install openai
    """

    def __init__(
        self,
        model: str = "text-embedding-3-small",
        api_key: Optional[str] = None,
        dim: int = 1536,
        embed_fn: Optional[Callable[[str], List[float]]] = None,
        # legacy alias kept for callers that pass model_name=
        model_name: Optional[str] = None,
    ):
        self.model = model_name or model
        self.dim = dim
        self._api_key = api_key
        self._embed_fn = embed_fn
        self._client = None

    def _get_client(self):
        if self._client is None:
            try:
                from openai import OpenAI
            except ImportError as exc:
                raise ImportError("openai package required: pip install openai") from exc
            self._client = OpenAI(api_key=self._api_key)
        return self._client

    def embed(self, text: str) -> List[float]:
        if self._embed_fn is not None:
            return self._embed_fn(text)
        response = self._get_client().embeddings.create(model=self.model, input=text)
        return response.data[0].embedding

    def embed_batch(self, texts: List[str]) -> List[List[float]]:
        if self._embed_fn is not None:
            return [self._embed_fn(t) for t in texts]
        response = self._get_client().embeddings.create(model=self.model, input=texts)
        return [item.embedding for item in response.data]

    def _mock_embed(self, text: str) -> List[float]:
        """Deterministic unit-length vector derived from text hash."""
        seed = int(hashlib.md5(text.encode()).hexdigest(), 16) % (2 ** 32)
        rng = random.Random(seed)
        vec = [rng.gauss(0, 1) for _ in range(self.dim)]
        norm = sum(x ** 2 for x in vec) ** 0.5 or 1.0
        return [x / norm for x in vec]


# Backward-compat alias
OpenAIEmbeddingProvider = EmbeddingProvider
