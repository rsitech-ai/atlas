"""Lexical post-RRF rerank (stdlib OSS; no neural dependency)."""

from __future__ import annotations

import math
import re
from hashlib import sha256
from json import dumps

from rsi_atlas_contracts import FusedEvidenceItem

_TOKEN = re.compile(r"[a-z0-9_]+", re.IGNORECASE)

RERANK_CONFIGURATION = {
    "method": "lexical_overlap_rerank_v1",
    "license": "stdlib",
    "k": 20,
}
RERANK_CONFIGURATION_HASH = sha256(
    dumps(RERANK_CONFIGURATION, sort_keys=True, separators=(",", ":")).encode("utf-8")
).hexdigest()


def _tokens(text: str) -> set[str]:
    return set(_TOKEN.findall(text.lower()))


def lexical_overlap_score(*, query: str, preview: str) -> float:
    """BM25-lite token overlap in [0, 1] using query-side IDF approximation."""
    q = _tokens(query)
    d = _tokens(preview)
    if not q or not d:
        return 0.0
    overlap = q & d
    if not overlap:
        return 0.0
    # ponytail: ceiling=no corpus IDF; upgrade=indexed collection stats
    idf = math.log(1.0 + len(q) / max(len(overlap), 1))
    return min(1.0, (len(overlap) / len(q)) * (1.0 + idf) / 3.0)


def rerank_fused_lexical(
    *,
    query: str,
    items: tuple[FusedEvidenceItem, ...],
    final_k: int = 20,
) -> tuple[FusedEvidenceItem, ...]:
    """Reorder fused items by fusion_score + lexical overlap; keep inspectable ranks."""
    scored: list[tuple[float, FusedEvidenceItem]] = []
    for item in items:
        lexical = lexical_overlap_score(query=query, preview=item.text_preview)
        scored.append((item.fusion_score + lexical, item))
    scored.sort(key=lambda pair: (-pair[0], pair[1].chunk_id))
    reranked: list[FusedEvidenceItem] = []
    for rank, (score, item) in enumerate(scored[:final_k], start=1):
        reranked.append(item.model_copy(update={"fusion_score": score, "fusion_rank": rank}))
    return tuple(reranked)


__all__ = [
    "RERANK_CONFIGURATION",
    "RERANK_CONFIGURATION_HASH",
    "lexical_overlap_score",
    "rerank_fused_lexical",
]
