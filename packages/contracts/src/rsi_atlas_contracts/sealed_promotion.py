"""Sealed-holdout production promotion contracts (§26.8 / §35)."""

from __future__ import annotations

from datetime import datetime, timedelta
from enum import StrEnum
from hashlib import sha256
from json import dumps
from typing import Literal, Self

from pydantic import Field, StrictBool, StrictInt, field_validator, model_validator

from rsi_atlas_contracts.document_parsing import DocumentContractModel
from rsi_atlas_contracts.evaluation import PromotionOutcome

_SHA256_PATTERN = r"^[0-9a-f]{64}$"
_EVIDENCE_ID_PATTERN = r"^sealed:[0-9a-f]{64}$"
_IDENTIFIER_PATTERN = r"^[a-z][a-z0-9_]{0,63}$"
_VERSION_PATTERN = r"^[0-9]+\.[0-9]+\.[0-9]+(?:-[a-z0-9.]+)?$"


def _require_utc(value: datetime, *, field_name: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() != timedelta(0):
        raise ValueError(f"{field_name} must be timezone-aware UTC")
    return value


def _canonical_json(payload: object) -> str:
    return dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


class SealedComponentKind(StrEnum):
    EMBEDDING = "embedding"
    RERANKER = "reranker"
    PARSER = "parser"
    CHUNK_POLICY = "chunk_policy"


class SealedPromotionStatus(StrEnum):
    """Lifecycle of a sealed promotion attempt."""

    FAIL_CLOSED = "fail_closed"
    CANDIDATE_ONLY = "candidate_only"
    PROMOTE_SHADOW = "promote_shadow"
    DEVELOPMENT_SEALED_PACKAGE = "development_sealed_package"
    PROMOTE_PRODUCTION = "promote_production"


REQUIRED_SEALED_GATES: frozenset[str] = frozenset(
    {
        "critical_deterministic_failures_zero",
        "holdout_split_present",
        "holdout_without_tuning_labels",
        "dataset_frozen",
        "component_governance_present",
    }
)


class SealedGateResult(DocumentContractModel):
    gate_id: str = Field(pattern=_IDENTIFIER_PATTERN)
    passed: StrictBool
    detail: str = Field(default="", max_length=512)


class SealedPromotionEvidence(DocumentContractModel):
    """Immutable evidence that a sealed holdout suite was evaluated.

    Presence alone does not authorize PRODUCTION. ``status`` must be
    ``promote_production`` and ``outcome`` must be ``promote``.
    """

    schema_version: Literal["rsi-atlas.sealed-promotion.v1"] = "rsi-atlas.sealed-promotion.v1"
    evidence_id: str = Field(pattern=_EVIDENCE_ID_PATTERN)
    component: SealedComponentKind
    candidate_id: str = Field(pattern=_IDENTIFIER_PATTERN)
    candidate_version: str = Field(pattern=_VERSION_PATTERN)
    dataset_id: str = Field(min_length=1, max_length=128)
    dataset_version: str = Field(pattern=_VERSION_PATTERN)
    dataset_content_hash: str = Field(pattern=_SHA256_PATTERN)
    evaluation_run_id: str = Field(min_length=1, max_length=128)
    outcome: PromotionOutcome
    status: SealedPromotionStatus
    gates: tuple[SealedGateResult, ...] = Field(min_length=1)
    critical_failure_count: StrictInt = Field(ge=0)
    created_at: datetime
    honesty_note: str = Field(
        default=(
            "synthetic fixtures authorize machinery only; owner-sealed corpus required for Proven"
        ),
        min_length=1,
        max_length=512,
    )

    @field_validator("created_at")
    @classmethod
    def _utc(cls, value: datetime) -> datetime:
        return _require_utc(value, field_name="created_at")

    @model_validator(mode="after")
    def _consistency(self) -> Self:
        gate_ids = {gate.gate_id for gate in self.gates}
        missing = REQUIRED_SEALED_GATES - gate_ids
        if missing:
            raise ValueError(f"sealed evidence missing required gates: {sorted(missing)}")
        failed = [gate.gate_id for gate in self.gates if not gate.passed]
        if self.status is SealedPromotionStatus.PROMOTE_PRODUCTION:
            if failed:
                raise ValueError("promote_production requires all recorded gates to pass")
            if self.critical_failure_count != 0:
                raise ValueError("promote_production requires zero critical failures")
            if self.outcome is not PromotionOutcome.PROMOTE:
                raise ValueError("promote_production requires outcome=promote")
        if self.status is SealedPromotionStatus.DEVELOPMENT_SEALED_PACKAGE:
            if failed:
                raise ValueError("development_sealed_package requires all recorded gates to pass")
            if self.critical_failure_count != 0:
                raise ValueError("development_sealed_package requires zero critical failures")
            if self.outcome is PromotionOutcome.PROMOTE:
                raise ValueError(
                    "development_sealed_package must not claim outcome=promote "
                    "(owner-sealed corpus required for PRODUCTION)"
                )
        if self.critical_failure_count > 0 and self.outcome in {
            PromotionOutcome.PROMOTE,
            PromotionOutcome.PROMOTE_FOR_SELECTED_TASK_ONLY,
        }:
            raise ValueError("critical failures cannot promote")
        return self

    def authorizes_production(self) -> bool:
        return (
            self.status is SealedPromotionStatus.PROMOTE_PRODUCTION
            and self.outcome is PromotionOutcome.PROMOTE
            and self.critical_failure_count == 0
            and all(gate.passed for gate in self.gates)
        )

    def is_development_sealed_package(self) -> bool:
        return (
            self.status is SealedPromotionStatus.DEVELOPMENT_SEALED_PACKAGE
            and self.critical_failure_count == 0
            and all(gate.passed for gate in self.gates)
        )


def sealed_evidence_id(
    *,
    component: SealedComponentKind,
    candidate_id: str,
    dataset_content_hash: str,
    evaluation_run_id: str,
    created_at: datetime,
) -> str:
    body = _canonical_json(
        {
            "candidate_id": candidate_id,
            "component": component.value,
            "created_at": created_at.isoformat().replace("+00:00", "Z"),
            "dataset_content_hash": dataset_content_hash,
            "evaluation_run_id": evaluation_run_id,
        }
    )
    return "sealed:" + sha256(body.encode("utf-8")).hexdigest()


__all__ = [
    "REQUIRED_SEALED_GATES",
    "SealedComponentKind",
    "SealedGateResult",
    "SealedPromotionEvidence",
    "SealedPromotionStatus",
    "sealed_evidence_id",
]
