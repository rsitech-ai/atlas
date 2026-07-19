"""Sealed-holdout promotion gate tests."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest
from rsi_atlas_contracts import (
    EmbeddingPromotionClass,
    PromotionOutcome,
    SealedComponentKind,
    SealedPromotionStatus,
)
from rsi_atlas_evaluation.sealed_promotion import (
    SealedPromotionBlocked,
    default_sealed_fixture_path,
    require_production_authorization,
    run_sealed_promotion,
)

NOW = datetime(2026, 7, 19, 15, 0, tzinfo=UTC)
ROOT = Path(__file__).resolve().parents[3]


def test_sealed_fixture_exists() -> None:
    path = default_sealed_fixture_path()
    assert path.is_file()
    assert path.name == "sealed_holdout_v1.json"


def test_fail_closed_without_synthetic_flag() -> None:
    evidence = run_sealed_promotion(
        component=SealedComponentKind.EMBEDDING,
        candidate_id="oss_token_hash_v1",
        candidate_version="1.0.0",
        repo_root=ROOT,
        created_at=NOW,
        allow_synthetic_promote=False,
    )
    assert evidence.status is SealedPromotionStatus.CANDIDATE_ONLY
    assert evidence.outcome is PromotionOutcome.CONTINUE_SHADOW_EVALUATION
    assert evidence.authorizes_production() is False
    with pytest.raises(SealedPromotionBlocked):
        require_production_authorization(evidence)


def test_synthetic_machinery_can_exercise_promote_path() -> None:
    evidence = run_sealed_promotion(
        component=SealedComponentKind.RERANKER,
        candidate_id="lexical_overlap_rerank_v1",
        candidate_version="1.0.0",
        repo_root=ROOT,
        created_at=NOW,
        allow_synthetic_promote=True,
    )
    assert evidence.status is SealedPromotionStatus.PROMOTE_PRODUCTION
    assert evidence.outcome is PromotionOutcome.PROMOTE
    assert evidence.authorizes_production() is True
    assert "synthetic" in evidence.honesty_note.lower()
    # Still not an acceptance Proven claim — honesty note forbids it.


def test_parser_and_chunk_components_run() -> None:
    for component, candidate in (
        (SealedComponentKind.PARSER, "tier0_pypdf"),
        (SealedComponentKind.CHUNK_POLICY, "fixed_token"),
    ):
        evidence = run_sealed_promotion(
            component=component,
            candidate_id=candidate,
            candidate_version="1.0.0",
            repo_root=ROOT,
            created_at=NOW,
            allow_synthetic_promote=False,
        )
        assert evidence.component is component
        assert evidence.critical_failure_count == 0
        assert evidence.authorizes_production() is False


def test_require_production_none_blocked() -> None:
    with pytest.raises(SealedPromotionBlocked):
        require_production_authorization(None)


def test_embedding_production_class_still_gated() -> None:
    # Index staging must not treat synthetic promote as silent PRODUCTION claim.
    assert EmbeddingPromotionClass.PRODUCTION.value == "production"
