"""Deterministic development embeddings (not production-promoted)."""

from __future__ import annotations

import math
from hashlib import sha256
from json import dumps

from rsi_atlas_contracts import (
    DEVELOPMENT_EMBEDDING_DIMENSIONS,
    EmbeddingModelIdentity,
    EmbeddingPromotionClass,
    validate_vector,
)

# ponytail: ceiling=hash-pseudo-embedding (not semantic); upgrade=governed ModelArtifact EMBEDDINGS
_POLICY = {
    "adapter": "deterministic_hash_v1",
    "dimensions": DEVELOPMENT_EMBEDDING_DIMENSIONS,
    "normalization": "l2",
}
_POLICY_HASH = sha256(
    dumps(_POLICY, sort_keys=True, separators=(",", ":")).encode("utf-8")
).hexdigest()

DEVELOPMENT_EMBEDDING_MODEL = EmbeddingModelIdentity(
    model_id="fixture_hash_v1",
    version="dev-1",
    dimensions=DEVELOPMENT_EMBEDDING_DIMENSIONS,
    normalization="l2",
    configuration_hash=_POLICY_HASH,
    promotion_class=EmbeddingPromotionClass.DEVELOPMENT_FIXTURE,
)


class EmbeddingError(ValueError):
    """Raised when development embedding inputs are invalid."""


class DeterministicEmbedder:
    """Map text to a fixed-dim L2 unit vector via SHA-256 expansion."""

    def __init__(self) -> None:
        self._cache: dict[str, tuple[float, ...]] = {}
        self.cache_hits = 0

    @property
    def model(self) -> EmbeddingModelIdentity:
        return DEVELOPMENT_EMBEDDING_MODEL

    @property
    def input_policy_hash(self) -> str:
        return _POLICY_HASH

    def embed_text(self, text: str) -> tuple[float, ...]:
        if not text or not text.strip():
            raise EmbeddingError("empty embedding text")
        text_hash = sha256(text.encode("utf-8")).hexdigest()
        cached = self._cache.get(text_hash)
        if cached is not None:
            self.cache_hits += 1
            return cached
        vector = _hash_to_unit_vector(text_hash, dimensions=DEVELOPMENT_EMBEDDING_DIMENSIONS)
        validate_vector(vector, dimensions=DEVELOPMENT_EMBEDDING_DIMENSIONS)
        self._cache[text_hash] = vector
        return vector


def _hash_to_unit_vector(digest_hex: str, *, dimensions: int) -> tuple[float, ...]:
    # Expand digest material until we have enough bytes for dimensions floats.
    material = digest_hex.encode("ascii")
    while len(material) < dimensions * 4:
        material += sha256(material).digest()
    components: list[float] = []
    for index in range(dimensions):
        offset = index * 4
        unsigned = int.from_bytes(material[offset : offset + 4], "big")
        # Map to (-1, 1) excluding exact zero via odd bias.
        centered = ((unsigned / 0xFFFFFFFF) * 2.0) - 1.0
        if centered == 0.0:
            centered = 1e-6
        components.append(centered)
    norm = math.sqrt(sum(value * value for value in components))
    if norm == 0.0:
        raise EmbeddingError("zero embedding norm")
    return tuple(value / norm for value in components)


__all__ = [
    "DEVELOPMENT_EMBEDDING_MODEL",
    "DeterministicEmbedder",
    "EmbeddingError",
]
