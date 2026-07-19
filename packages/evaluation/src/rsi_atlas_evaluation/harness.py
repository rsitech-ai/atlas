"""Offline evaluation harness over frozen fixture datasets."""

from __future__ import annotations

from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from typing import Any

from rsi_atlas_contracts import (
    EVALUATOR_ORDER,
    DatasetStatus,
    EvaluationDataset,
    EvaluationExample,
    EvaluationRun,
    EvaluationRunStatus,
    EvaluatorResult,
    ExperimentManifest,
    PromotionDecision,
    evaluation_run_id,
    experiment_id,
)

from rsi_atlas_evaluation.errors import DatasetLoadError, JudgeCalibrationBlocked
from rsi_atlas_evaluation.evaluators import run_deterministic_evaluators
from rsi_atlas_evaluation.judges import refuse_uncalibrated_judge
from rsi_atlas_evaluation.promotion import decide_promotion


def load_dataset(path: Path) -> EvaluationDataset:
    """Load and validate a frozen evaluation dataset JSON fixture."""
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise DatasetLoadError(f"cannot read dataset: {path}") from exc
    try:
        dataset = EvaluationDataset.model_validate_json(raw)
    except ValueError as exc:
        raise DatasetLoadError(f"invalid dataset json: {path}") from exc
    if dataset.status is not DatasetStatus.FROZEN:
        raise DatasetLoadError("offline harness requires frozen datasets")
    return dataset


def default_fixture_path() -> Path:
    """Repository fixture for retrieval regression v1."""
    return (
        Path(__file__).resolve().parents[4]
        / "fixtures"
        / "evaluation"
        / "retrieval_regression_v1.json"
    )


def _actual_for_example(example: EvaluationExample) -> dict[str, Any]:
    """Development harness uses expected payload as the candidate actual (self-check).

    ponytail: ceiling is fixture self-consistency only; upgrade path is wiring real
    system outputs per example_id from a frozen run store.
    """
    return dict(example.expected_payload)


def _collapse_results(all_results: list[EvaluatorResult]) -> tuple[EvaluatorResult, ...]:
    """One result per kind in EVALUATOR_ORDER; stop after the first failed kind."""
    seen = {result.kind for result in all_results}
    collapsed: list[EvaluatorResult] = []
    for kind in EVALUATOR_ORDER:
        if kind not in seen:
            continue
        failed = [result for result in all_results if result.kind == kind and not result.passed]
        if failed:
            collapsed.append(failed[0])
            break
        collapsed.append(next(result for result in all_results if result.kind == kind))
    return tuple(collapsed)


def run_offline_evaluation(
    dataset: EvaluationDataset,
    *,
    created_at: datetime | None = None,
    include_judge: bool = False,
    actuals: dict[str, dict[str, Any]] | None = None,
) -> tuple[EvaluationRun, PromotionDecision]:
    """Run deterministic evaluators; optionally attempt (and block) LLM judge."""
    now = created_at or datetime.now(tz=UTC)
    exp = experiment_id(
        source_snapshot_hash=dataset.source_snapshot_hash,
        dataset_id=dataset.dataset_id,
        dataset_version=dataset.version,
    )
    ExperimentManifest(
        experiment_id=exp,
        source_snapshot_hash=dataset.source_snapshot_hash,
        dataset_id=dataset.dataset_id,
        dataset_version=dataset.version,
        parser_version="tier0_pypdf",
        chunker_version="fixed_token",
        embedding_version="fixture_hash",
        retrieval_version="hybrid_rrf_dev",
        hardware_class="24gb",
        created_at=now,
    )
    all_results: list[EvaluatorResult] = []
    critical = 0
    for example in dataset.examples:
        actual = (actuals or {}).get(example.example_id) or _actual_for_example(example)
        results = run_deterministic_evaluators(example, actual)
        all_results.extend(results)
        critical += sum(1 for result in results if not result.passed)

    status = EvaluationRunStatus.COMPLETED
    if include_judge:
        try:
            refuse_uncalibrated_judge()
        except JudgeCalibrationBlocked:
            status = EvaluationRunStatus.BLOCKED

    run = EvaluationRun(
        run_id=evaluation_run_id(experiment_id=exp, created_at=now),
        experiment_id=exp,
        status=status,
        results=_collapse_results(all_results),
        critical_failure_count=critical,
        created_at=now,
        completed_at=now,
    )
    decision = decide_promotion(run, created_at=now)
    return run, decision


def dataset_content_hash(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()
