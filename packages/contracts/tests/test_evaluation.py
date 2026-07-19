"""Strict Phase 6 evaluation-plane contract tests."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError
from rsi_atlas_contracts.evaluation import (
    BLOCKED_EVALUATOR_KINDS,
    DEVELOPMENT_EVALUATOR_KINDS,
    EVALUATOR_ORDER,
    DatasetSplit,
    DatasetStatus,
    EvaluationDataset,
    EvaluationExample,
    EvaluationRun,
    EvaluationRunStatus,
    EvaluatorKind,
    EvaluatorResult,
    ExperimentManifest,
    JudgeCalibrationGate,
    JudgeCalibrationStatus,
    PromotionDecision,
    PromotionOutcome,
    evaluation_run_id,
    experiment_id,
    promotion_decision_id,
)

NOW = datetime(2026, 7, 19, 12, 0, tzinfo=UTC)
SNAP = "a" * 64


def _example(
    *,
    example_id: str = "ex1",
    split: DatasetSplit = DatasetSplit.REGRESSION,
    labels: tuple[str, ...] = (),
) -> EvaluationExample:
    return EvaluationExample(
        example_id=example_id,
        split=split,
        input_payload={"query": "what is x"},
        expected_payload={"abstain": False},
        labels=labels,
    )


def test_evaluator_order_is_deterministic_before_judges() -> None:
    assert EVALUATOR_ORDER[0] == EvaluatorKind.SCHEMA
    assert EvaluatorKind.LLM_JUDGE in BLOCKED_EVALUATOR_KINDS
    assert EvaluatorKind.SCHEMA in DEVELOPMENT_EVALUATOR_KINDS
    assert EVALUATOR_ORDER.index(EvaluatorKind.DETERMINISTIC_RULE) < EVALUATOR_ORDER.index(
        EvaluatorKind.LLM_JUDGE
    )


def test_frozen_holdout_rejects_tuning_labels() -> None:
    with pytest.raises(ValidationError, match="holdout"):
        EvaluationDataset(
            dataset_id="dataset:retrieval_regression",
            version="1.0.0",
            purpose="retrieval regression",
            task_family="retrieval",
            source_snapshot_hash=SNAP,
            status=DatasetStatus.FROZEN,
            examples=(_example(example_id="h1", split=DatasetSplit.HOLDOUT, labels=("tune",)),),
        )


def test_dataset_accepts_frozen_regression_fixture() -> None:
    dataset = EvaluationDataset(
        dataset_id="dataset:retrieval_regression",
        version="1.0.0",
        purpose="retrieval regression",
        task_family="retrieval",
        source_snapshot_hash=SNAP,
        status=DatasetStatus.FROZEN,
        examples=(_example(), _example(example_id="ex2", split=DatasetSplit.ADVERSARIAL)),
    )
    assert dataset.status is DatasetStatus.FROZEN


def test_blocked_evaluator_cannot_pass() -> None:
    with pytest.raises(ValidationError, match="blocked"):
        EvaluatorResult(kind=EvaluatorKind.LLM_JUDGE, passed=True)


def test_failed_result_requires_failure_class() -> None:
    with pytest.raises(ValidationError, match="failure_class"):
        EvaluatorResult(kind=EvaluatorKind.SCHEMA, passed=False)


def test_run_rejects_out_of_order_evaluators() -> None:
    exp = experiment_id(
        source_snapshot_hash=SNAP,
        dataset_id="dataset:retrieval_regression",
        dataset_version="1.0.0",
    )
    run_id = evaluation_run_id(experiment_id=exp, created_at=NOW)
    with pytest.raises(ValidationError, match="EVALUATOR_ORDER"):
        EvaluationRun(
            run_id=run_id,
            experiment_id=exp,
            status=EvaluationRunStatus.COMPLETED,
            results=(
                EvaluatorResult(kind=EvaluatorKind.DETERMINISTIC_RULE, passed=True),
                EvaluatorResult(kind=EvaluatorKind.SCHEMA, passed=True),
            ),
            critical_failure_count=0,
            created_at=NOW,
            completed_at=NOW,
        )


def test_later_evaluator_cannot_erase_earlier_failure() -> None:
    exp = experiment_id(
        source_snapshot_hash=SNAP,
        dataset_id="dataset:retrieval_regression",
        dataset_version="1.0.0",
    )
    run_id = evaluation_run_id(experiment_id=exp, created_at=NOW)
    with pytest.raises(ValidationError, match="cannot erase"):
        EvaluationRun(
            run_id=run_id,
            experiment_id=exp,
            status=EvaluationRunStatus.COMPLETED,
            results=(
                EvaluatorResult(
                    kind=EvaluatorKind.SCHEMA,
                    passed=False,
                    failure_class="schema_invalid",
                ),
                EvaluatorResult(kind=EvaluatorKind.DETERMINISTIC_RULE, passed=True),
            ),
            critical_failure_count=1,
            created_at=NOW,
            completed_at=NOW,
        )


def test_promotion_blocks_on_critical_failures() -> None:
    exp = experiment_id(
        source_snapshot_hash=SNAP,
        dataset_id="dataset:retrieval_regression",
        dataset_version="1.0.0",
    )
    run_id = evaluation_run_id(experiment_id=exp, created_at=NOW)
    with pytest.raises(ValidationError, match="critical"):
        PromotionDecision(
            decision_id=promotion_decision_id(
                run_id=run_id, outcome=PromotionOutcome.PROMOTE, created_at=NOW
            ),
            run_id=run_id,
            outcome=PromotionOutcome.PROMOTE,
            critical_failure_count=1,
            reasons=("attempted promote",),
            created_at=NOW,
        )


def test_promotion_reject_ok_with_critical_failures() -> None:
    exp = experiment_id(
        source_snapshot_hash=SNAP,
        dataset_id="dataset:retrieval_regression",
        dataset_version="1.0.0",
    )
    run_id = evaluation_run_id(experiment_id=exp, created_at=NOW)
    decision = PromotionDecision(
        decision_id=promotion_decision_id(
            run_id=run_id, outcome=PromotionOutcome.REJECT, created_at=NOW
        ),
        run_id=run_id,
        outcome=PromotionOutcome.REJECT,
        critical_failure_count=2,
        reasons=("schema_invalid", "citation_missing"),
        created_at=NOW,
    )
    assert decision.outcome is PromotionOutcome.REJECT


def test_judge_calibration_gate_fail_closed() -> None:
    gate = JudgeCalibrationGate()
    assert gate.status is JudgeCalibrationStatus.BLOCKED_UNCALIBRATED
    with pytest.raises(ValidationError, match="blocked"):
        JudgeCalibrationGate(status=JudgeCalibrationStatus.CALIBRATED)


def test_experiment_manifest_requires_utc() -> None:
    exp = experiment_id(
        source_snapshot_hash=SNAP,
        dataset_id="dataset:retrieval_regression",
        dataset_version="1.0.0",
    )
    manifest = ExperimentManifest(
        experiment_id=exp,
        source_snapshot_hash=SNAP,
        dataset_id="dataset:retrieval_regression",
        dataset_version="1.0.0",
        parser_version="tier0_pypdf",
        chunker_version="fixed_token",
        embedding_version="fixture_hash",
        retrieval_version="hybrid_rrf_dev",
        hardware_class="24gb",
        created_at=NOW,
    )
    assert manifest.hardware_class == "24gb"
    with pytest.raises(ValidationError, match="UTC"):
        ExperimentManifest(
            experiment_id=exp,
            source_snapshot_hash=SNAP,
            dataset_id="dataset:retrieval_regression",
            dataset_version="1.0.0",
            parser_version="tier0_pypdf",
            chunker_version="fixed_token",
            embedding_version="fixture_hash",
            retrieval_version="hybrid_rrf_dev",
            hardware_class="24gb",
            created_at=datetime(2026, 7, 19, 12, 0),
        )
