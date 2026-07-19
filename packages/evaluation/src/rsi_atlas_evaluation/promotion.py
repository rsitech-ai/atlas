"""Promotion gate for evaluation runs."""

from __future__ import annotations

from datetime import datetime

from rsi_atlas_contracts import (
    EvaluationRun,
    PromotionDecision,
    PromotionOutcome,
    promotion_decision_id,
)

CRITICAL_FAILURE_CLASSES = frozenset(
    {
        "schema_invalid",
        "rule_mismatch",
        "numerical_mismatch",
        "citation_missing",
        "historical_leakage",
        "cross_workspace_leakage",
    }
)


def decide_promotion(run: EvaluationRun, *, created_at: datetime) -> PromotionDecision:
    """Fail closed: any critical deterministic failure yields reject."""
    critical = 0
    reasons: list[str] = []
    for result in run.results:
        if not result.passed and result.failure_class in CRITICAL_FAILURE_CLASSES:
            critical += 1
            reasons.append(result.failure_class)
    if critical > 0:
        outcome = PromotionOutcome.REJECT
        if not reasons:
            reasons = ["critical_deterministic_failure"]
    elif run.status.value == "blocked":
        outcome = PromotionOutcome.REQUIRE_HUMAN_REVIEW
        reasons = ["evaluation_blocked"]
    else:
        outcome = PromotionOutcome.REQUIRE_HUMAN_REVIEW
        reasons = ["development_slice_requires_human_review"]
    return PromotionDecision(
        decision_id=promotion_decision_id(
            run_id=run.run_id, outcome=outcome, created_at=created_at
        ),
        run_id=run.run_id,
        outcome=outcome,
        critical_failure_count=critical,
        reasons=tuple(reasons),
        created_at=created_at,
    )
