"""Offline evaluation harness tests."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest
from rsi_atlas_contracts import EvaluationRunStatus, PromotionOutcome
from rsi_atlas_evaluation import (
    JudgeCalibrationBlocked,
    default_fixture_path,
    load_dataset,
    refuse_uncalibrated_judge,
    run_offline_evaluation,
)

NOW = datetime(2026, 7, 19, 14, 0, tzinfo=UTC)


def test_load_frozen_fixture() -> None:
    dataset = load_dataset(default_fixture_path())
    assert dataset.dataset_id == "dataset:retrieval_regression"
    assert len(dataset.examples) == 3


def test_offline_run_passes_self_consistent_fixture() -> None:
    dataset = load_dataset(default_fixture_path())
    run, decision = run_offline_evaluation(dataset, created_at=NOW)
    assert run.status is EvaluationRunStatus.COMPLETED
    assert run.critical_failure_count == 0
    assert all(result.passed for result in run.results)
    assert decision.outcome is PromotionOutcome.REQUIRE_HUMAN_REVIEW


def test_offline_run_rejects_on_mismatch() -> None:
    dataset = load_dataset(default_fixture_path())
    run, decision = run_offline_evaluation(
        dataset,
        created_at=NOW,
        actuals={
            "pass_cite": {"abstain": False, "citation_ids": [], "score": 1},
            "adversarial_empty": {"abstain": True, "citation_ids": [], "score": 0},
            "holdout_silent": {"abstain": False, "citation_ids": ["cite_b"], "score": 1},
        },
    )
    assert run.critical_failure_count >= 1
    assert decision.outcome is PromotionOutcome.REJECT
    assert "citation_missing" in decision.reasons or "rule_mismatch" in decision.reasons


def test_judge_path_blocks() -> None:
    with pytest.raises(JudgeCalibrationBlocked):
        refuse_uncalibrated_judge()
    dataset = load_dataset(default_fixture_path())
    run, decision = run_offline_evaluation(dataset, created_at=NOW, include_judge=True)
    assert run.status is EvaluationRunStatus.BLOCKED
    assert decision.outcome in {
        PromotionOutcome.REQUIRE_HUMAN_REVIEW,
        PromotionOutcome.REJECT,
    }


def test_default_fixture_exists() -> None:
    path = default_fixture_path()
    assert path.is_file()
    assert path.name == "retrieval_regression_v1.json"
    assert Path("fixtures/evaluation") in path.parents or "fixtures" in path.parts
