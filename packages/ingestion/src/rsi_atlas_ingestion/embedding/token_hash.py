"""Offline OSS token-hash embeddings (candidate; no network; no model download)."""

from __future__ import annotations

import math
import re
from hashlib import sha256
from json import dumps

from rsi_atlas_contracts import (
    DEVELOPMENT_EMBEDDING_DIMENSIONS,
    EmbeddingModelIdentity,
    EmbeddingPromotionClass,
    validate_vector,
)

from rsi_atlas_ingestion.embedding.deterministic import EmbeddingError

_TOKEN = re.compile(r"[a-z0-9_]+", re.IGNORECASE)

_POLICY = {
    "adapter": "oss_token_hash_v1",
    "dimensions": DEVELOPMENT_EMBEDDING_DIMENSIONS,
    "normalization": "l2",
    "ngram": "1-2",
    "license": "stdlib",
}
_POLICY_HASH = sha256(
    dumps(_POLICY, sort_keys=True, separators=(",", ":")).encode("utf-8")
).hexdigest()

OSS_TOKEN_HASH_MODEL = EmbeddingModelIdentity(
    model_id="oss_token_hash_v1",
    version="cand-1",
    dimensions=DEVELOPMENT_EMBEDDING_DIMENSIONS,
    normalization="l2",
    configuration_hash=_POLICY_HASH,
    promotion_class=EmbeddingPromotionClass.CANDIDATE,
)


class TokenHashEmbedder:
    """Hashed bag-of-token n-grams → fixed-dim L2 unit vector (offline OSS).

    ponytail: ceiling=not semantic MiniLM; upgrade=OfflineOnnxEmbedder + pinned artifact
    """

    def __init__(self) -> None:
        self._cache: dict[str, tuple[float, ...]] = {}

    @property
    def model(self) -> EmbeddingModelIdentity:
        return OSS_TOKEN_HASH_MODEL

    @property
    def input_policy_hash(self) -> str:
        return _POLICY_HASH

    def embed_text(self, text: str) -> tuple[float, ...]:
        if not text or not text.strip():
            raise EmbeddingError("empty embedding text")
        text_hash = sha256(text.encode("utf-8")).hexdigest()
        cached = self._cache.get(text_hash)
        if cached is not None:
            return cached
        vector = _token_hash_vector(text, dimensions=DEVELOPMENT_EMBEDDING_DIMENSIONS)
        validate_vector(vector, dimensions=DEVELOPMENT_EMBEDDING_DIMENSIONS)
        self._cache[text_hash] = vector
        return vector


def _token_hash_vector(text: str, *, dimensions: int) -> tuple[float, ...]:
    tokens = _TOKEN.findall(text.lower())
    if not tokens:
        raise EmbeddingError("no tokens for embedding")
    grams: list[str] = list(tokens)
    grams.extend(f"{tokens[i]}_{tokens[i + 1]}" for i in range(len(tokens) - 1))
    components = [0.0] * dimensions
    for gram in grams:
        digest = sha256(gram.encode("utf-8")).digest()
        index = int.from_bytes(digest[:4], "big") % dimensions
        sign = 1.0 if digest[4] % 2 == 0 else -1.0
        components[index] += sign
    norm = math.sqrt(sum(value * value for value in components))
    if norm == 0.0:
        raise EmbeddingError("zero embedding norm")
    return tuple(value / norm for value in components)


__all__ = [
    "OSS_TOKEN_HASH_MODEL",
    "TokenHashEmbedder",
]
