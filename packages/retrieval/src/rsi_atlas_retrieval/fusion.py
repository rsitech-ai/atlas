"""Intent-weighted reciprocal-rank fusion with inspectable component ranks."""

from __future__ import annotations

from hashlib import sha256
from json import dumps

from rsi_atlas_contracts import (
    ComponentRank,
    EvidenceCandidate,
    FusedEvidenceItem,
    QueryFamily,
    RetrievalDataPlane,
)

# ponytail: ceiling=fixed RRF + lexical overlap rerank; upgrade=governed ONNX cross-encoder
_DEFAULT_WEIGHTS: dict[RetrievalDataPlane, float] = {
    RetrievalDataPlane.DENSE_DOCUMENT: 1.0,
    RetrievalDataPlane.LEXICAL: 1.0,
    RetrievalDataPlane.EXACT_IDENTIFIER: 1.5,
}

_FAMILY_WEIGHT_OVERRIDES: dict[QueryFamily, dict[RetrievalDataPlane, float]] = {
    QueryFamily.EXACT_LOOKUP: {
        RetrievalDataPlane.EXACT_IDENTIFIER: 2.0,
        RetrievalDataPlane.LEXICAL: 1.2,
        RetrievalDataPlane.DENSE_DOCUMENT: 0.5,
    },
    QueryFamily.NARRATIVE_EXPLANATION: {
        RetrievalDataPlane.DENSE_DOCUMENT: 1.2,
        RetrievalDataPlane.LEXICAL: 1.0,
        RetrievalDataPlane.EXACT_IDENTIFIER: 0.8,
    },
}

_RRF_K = 60

FUSION_CONFIGURATION = {
    "method": "intent_weighted_rrf_v1",
    "k": _RRF_K,
    "post_rrf_rerank": "lexical_overlap_rerank_v1",
    "default_weights": {plane.value: weight for plane, weight in _DEFAULT_WEIGHTS.items()},
    "family_overrides": {
        family.value: {plane.value: weight for plane, weight in weights.items()}
        for family, weights in _FAMILY_WEIGHT_OVERRIDES.items()
    },
}
FUSION_CONFIGURATION_HASH = sha256(
    dumps(FUSION_CONFIGURATION, sort_keys=True, separators=(",", ":")).encode("utf-8")
).hexdigest()


def fuse_candidates_rrf(
    *,
    candidates_by_plane: dict[RetrievalDataPlane, tuple[EvidenceCandidate, ...]],
    query_family: QueryFamily,
    final_k: int = 20,
) -> tuple[FusedEvidenceItem, ...]:
    """Fuse per-plane candidates with inspectable component ranks."""
    weights = dict(_DEFAULT_WEIGHTS)
    weights.update(_FAMILY_WEIGHT_OVERRIDES.get(query_family, {}))

    scores: dict[str, float] = {}
    components: dict[str, list[ComponentRank]] = {}
    exemplars: dict[str, EvidenceCandidate] = {}

    for plane, candidates in candidates_by_plane.items():
        weight = weights.get(plane, 1.0)
        for candidate in candidates:
            chunk_id = candidate.chunk_id
            contribution = weight / (_RRF_K + candidate.rank)
            scores[chunk_id] = scores.get(chunk_id, 0.0) + contribution
            components.setdefault(chunk_id, []).append(
                ComponentRank(
                    data_plane=plane,
                    rank=candidate.rank,
                    raw_score=candidate.raw_score,
                )
            )
            previous = exemplars.get(chunk_id)
            if previous is None or candidate.reliability_score > previous.reliability_score:
                exemplars[chunk_id] = candidate

    ordered = sorted(scores.items(), key=lambda item: (-item[1], item[0]))[:final_k]
    fused: list[FusedEvidenceItem] = []
    for fusion_rank, (chunk_id, fusion_score) in enumerate(ordered, start=1):
        candidate = exemplars[chunk_id]
        fused.append(
            FusedEvidenceItem(
                chunk_id=chunk_id,
                document_version_id=candidate.document_version_id,
                chunk_set_id=candidate.chunk_set_id,
                publication_id=candidate.publication_id,
                index_version_id=candidate.index_version_id,
                item_kind=candidate.item_kind,
                fusion_score=fusion_score,
                fusion_rank=fusion_rank,
                reliability_score=candidate.reliability_score,
                component_ranks=tuple(components[chunk_id]),
                excerpt_hash=candidate.excerpt_hash,
                text_preview=candidate.text_preview,
            )
        )
    return tuple(fused)
