"""Strict evaluation-plane contracts for Phase 6 (section 26 development slice)."""

from __future__ import annotations

import re
from datetime import datetime, timedelta
from enum import StrEnum
from hashlib import sha256
from json import dumps
from typing import Literal, Self

from pydantic import Field, StrictBool, StrictFloat, StrictInt, field_validator, model_validator

from rsi_atlas_contracts.document_parsing import DocumentContractModel

_SHA256_PATTERN = r"^[0-9a-f]{64}$"
_DATASET_ID_PATTERN = r"^dataset:[a-z][a-z0-9_]{0,63}$"
_EXPERIMENT_ID_PATTERN = r"^experiment:[0-9a-f]{64}$"
_RUN_ID_PATTERN = r"^evalrun:[0-9a-f]{64}$"
_DECISION_ID_PATTERN = r"^promotion:[0-9a-f]{64}$"
_IDENTIFIER_PATTERN = r"^[a-z][a-z0-9_]{0,63}$"
_VERSION_PATTERN = r"^[0-9]+\.[0-9]+\.[0-9]+(?:-[a-z0-9.]+)?$"


def _require_utc(value: datetime, *, field_name: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() != timedelta(0):
        raise ValueError(f"{field_name} must be timezone-aware UTC")
    return value


def _canonical_json(payload: object) -> str:
    return dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


class DatasetSplit(StrEnum):
    DEVELOPMENT = "development"
    CALIBRATION = "calibration"
    REGRESSION = "regression"
    ADVERSARIAL = "adversarial"
    HOLDOUT = "holdout"
    SHADOW_PRODUCTION = "shadow_production"


REQUIRED_DATASET_SPLITS = frozenset(DatasetSplit)


class DatasetStatus(StrEnum):
    DRAFT = "draft"
    FROZEN = "frozen"
    SUPERSEDED = "superseded"
    BLOCKED = "blocked"


class EvaluatorKind(StrEnum):
    SCHEMA = "schema"
    DETERMINISTIC_RULE = "deterministic_rule"
    EXACT_NUMERICAL = "exact_numerical"
    RETRIEVAL_CITATION = "retrieval_citation"
    STATISTICAL = "statistical"
    LLM_JUDGE = "llm_judge"
    HUMAN_REVIEW = "human_review"


EVALUATOR_ORDER: tuple[EvaluatorKind, ...] = (
    EvaluatorKind.SCHEMA,
    EvaluatorKind.DETERMINISTIC_RULE,
    EvaluatorKind.EXACT_NUMERICAL,
    EvaluatorKind.RETRIEVAL_CITATION,
    EvaluatorKind.STATISTICAL,
    EvaluatorKind.LLM_JUDGE,
    EvaluatorKind.HUMAN_REVIEW,
)

DEVELOPMENT_EVALUATOR_KINDS = frozenset(
    {
        EvaluatorKind.SCHEMA,
        EvaluatorKind.DETERMINISTIC_RULE,
        EvaluatorKind.EXACT_NUMERICAL,
        EvaluatorKind.RETRIEVAL_CITATION,
    }
)

BLOCKED_EVALUATOR_KINDS = frozenset(EvaluatorKind) - DEVELOPMENT_EVALUATOR_KINDS


class EvaluationRunStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    BLOCKED = "blocked"


class PromotionOutcome(StrEnum):
    PROMOTE = "promote"
    PROMOTE_FOR_SELECTED_TASK_ONLY = "promote_for_selected_task_only"
    CONTINUE_SHADOW_EVALUATION = "continue_shadow_evaluation"
    REJECT = "reject"
    REQUIRE_HUMAN_REVIEW = "require_human_review"


class JudgeCalibrationStatus(StrEnum):
    BLOCKED_UNCALIBRATED = "blocked_judge_uncalibrated"
    CALIBRATED = "calibrated"


class EvaluationExample(DocumentContractModel):
    example_id: str = Field(pattern=_IDENTIFIER_PATTERN)
    split: DatasetSplit
    input_payload: dict[str, object]
    expected_payload: dict[str, object]
    labels: tuple[str, ...] = ()

    @field_validator("labels")
    @classmethod
    def _labels(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        for label in value:
            if not re.fullmatch(_IDENTIFIER_PATTERN, label):
                raise ValueError("example label is invalid")
        return value


class EvaluationDataset(DocumentContractModel):
    dataset_id: str = Field(pattern=_DATASET_ID_PATTERN)
    version: str = Field(pattern=_VERSION_PATTERN)
    purpose: str = Field(min_length=1, max_length=256)
    task_family: str = Field(pattern=_IDENTIFIER_PATTERN)
    source_snapshot_hash: str = Field(pattern=_SHA256_PATTERN)
    status: DatasetStatus
    examples: tuple[EvaluationExample, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def _splits_and_holdout(self) -> Self:
        splits = {example.split for example in self.examples}
        if not splits:
            raise ValueError("dataset must include at least one example")
        # Development fixtures may ship a subset; require identity uniqueness.
        ids = [example.example_id for example in self.examples]
        if len(ids) != len(set(ids)):
            raise ValueError("dataset example_id values must be unique")
        if self.status == DatasetStatus.FROZEN and DatasetSplit.HOLDOUT in splits:
            # Holdout examples must not carry tuning labels in frozen sets.
            for example in self.examples:
                if example.split == DatasetSplit.HOLDOUT and example.labels:
                    raise ValueError("holdout examples must not carry tuning labels")
        return self


class EvaluatorResult(DocumentContractModel):
    kind: EvaluatorKind
    passed: StrictBool
    failure_class: str | None = Field(default=None, pattern=_IDENTIFIER_PATTERN)
    score: StrictFloat | None = None
    detail: str = Field(default="", max_length=512)

    @model_validator(mode="after")
    def _failure_requires_class(self) -> Self:
        if not self.passed and self.failure_class is None:
            raise ValueError("failed evaluator result requires failure_class")
        if self.passed and self.failure_class is not None:
            raise ValueError("passed evaluator result must not set failure_class")
        if self.kind in BLOCKED_EVALUATOR_KINDS and self.passed:
            raise ValueError(f"blocked evaluator kind cannot pass: {self.kind}")
        return self


class ExperimentManifest(DocumentContractModel):
    experiment_id: str = Field(pattern=_EXPERIMENT_ID_PATTERN)
    source_snapshot_hash: str = Field(pattern=_SHA256_PATTERN)
    dataset_id: str = Field(pattern=_DATASET_ID_PATTERN)
    dataset_version: str = Field(pattern=_VERSION_PATTERN)
    parser_version: str = Field(pattern=_IDENTIFIER_PATTERN)
    chunker_version: str = Field(pattern=_IDENTIFIER_PATTERN)
    embedding_version: str = Field(pattern=_IDENTIFIER_PATTERN)
    retrieval_version: str = Field(pattern=_IDENTIFIER_PATTERN)
    hardware_class: Literal["24gb", "32gb", "36gb"]
    created_at: datetime

    @field_validator("created_at")
    @classmethod
    def _utc(cls, value: datetime) -> datetime:
        return _require_utc(value, field_name="created_at")


class EvaluationRun(DocumentContractModel):
    run_id: str = Field(pattern=_RUN_ID_PATTERN)
    experiment_id: str = Field(pattern=_EXPERIMENT_ID_PATTERN)
    status: EvaluationRunStatus
    results: tuple[EvaluatorResult, ...] = ()
    critical_failure_count: StrictInt = Field(ge=0)
    created_at: datetime
    completed_at: datetime | None = None

    @field_validator("created_at", "completed_at")
    @classmethod
    def _utc(cls, value: datetime | None) -> datetime | None:
        if value is None:
            return None
        return _require_utc(value, field_name="timestamp")

    @model_validator(mode="after")
    def _order_and_completion(self) -> Self:
        if self.results:
            kinds = [result.kind for result in self.results]
            order_index = {kind: index for index, kind in enumerate(EVALUATOR_ORDER)}
            positions = [order_index[kind] for kind in kinds]
            if positions != sorted(positions):
                raise ValueError("evaluator results must follow EVALUATOR_ORDER")
            # A later evaluator cannot erase an earlier deterministic failure.
            early_kinds = {
                EvaluatorKind.SCHEMA,
                EvaluatorKind.DETERMINISTIC_RULE,
                EvaluatorKind.EXACT_NUMERICAL,
                EvaluatorKind.RETRIEVAL_CITATION,
            }
            saw_failure = False
            for result in self.results:
                if saw_failure and result.passed:
                    raise ValueError("later evaluator cannot erase earlier deterministic failure")
                if result.kind in early_kinds and not result.passed:
                    saw_failure = True
        if self.status == EvaluationRunStatus.COMPLETED and self.completed_at is None:
            raise ValueError("completed run requires completed_at")
        return self


class PromotionDecision(DocumentContractModel):
    decision_id: str = Field(pattern=_DECISION_ID_PATTERN)
    run_id: str = Field(pattern=_RUN_ID_PATTERN)
    outcome: PromotionOutcome
    critical_failure_count: StrictInt = Field(ge=0)
    reasons: tuple[str, ...] = Field(min_length=1)
    created_at: datetime

    @field_validator("created_at")
    @classmethod
    def _utc(cls, value: datetime) -> datetime:
        return _require_utc(value, field_name="created_at")

    @model_validator(mode="after")
    def _critical_blocks_promote(self) -> Self:
        if self.critical_failure_count > 0 and self.outcome in {
            PromotionOutcome.PROMOTE,
            PromotionOutcome.PROMOTE_FOR_SELECTED_TASK_ONLY,
        }:
            raise ValueError("critical failures cannot promote")
        for reason in self.reasons:
            if not reason or len(reason) > 256:
                raise ValueError("promotion reason is invalid")
        return self


class JudgeCalibrationGate(DocumentContractModel):
    status: JudgeCalibrationStatus = JudgeCalibrationStatus.BLOCKED_UNCALIBRATED
    reason: str = "blocked_judge_uncalibrated"

    @model_validator(mode="after")
    def _development_blocked(self) -> Self:
        if self.status != JudgeCalibrationStatus.BLOCKED_UNCALIBRATED:
            raise ValueError("judge calibration remains blocked in development")
        if self.reason != "blocked_judge_uncalibrated":
            raise ValueError("judge calibration reason must be blocked_judge_uncalibrated")
        return self


def experiment_id(*, source_snapshot_hash: str, dataset_id: str, dataset_version: str) -> str:
    body = _canonical_json(
        {
            "dataset_id": dataset_id,
            "dataset_version": dataset_version,
            "source_snapshot_hash": source_snapshot_hash,
        }
    )
    return "experiment:" + sha256(body.encode("utf-8")).hexdigest()


def evaluation_run_id(*, experiment_id: str, created_at: datetime) -> str:
    body = _canonical_json(
        {
            "created_at": created_at.isoformat().replace("+00:00", "Z"),
            "experiment_id": experiment_id,
        }
    )
    return "evalrun:" + sha256(body.encode("utf-8")).hexdigest()


def promotion_decision_id(*, run_id: str, outcome: PromotionOutcome, created_at: datetime) -> str:
    body = _canonical_json(
        {
            "created_at": created_at.isoformat().replace("+00:00", "Z"),
            "outcome": outcome.value,
            "run_id": run_id,
        }
    )
    return "promotion:" + sha256(body.encode("utf-8")).hexdigest()
