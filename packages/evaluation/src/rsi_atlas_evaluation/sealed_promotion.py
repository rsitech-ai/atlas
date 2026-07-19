"""Fail-closed sealed-holdout promotion for §35 selection-by-evaluation components."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from rsi_atlas_contracts import (
    DatasetSplit,
    DatasetStatus,
    EvaluationDataset,
    EvaluationRunStatus,
    PromotionOutcome,
    SealedComponentKind,
    SealedGateResult,
    SealedPromotionEvidence,
    SealedPromotionStatus,
    sealed_evidence_id,
)

from rsi_atlas_evaluation.errors import EvaluationError
from rsi_atlas_evaluation.harness import dataset_content_hash, load_dataset, run_offline_evaluation
from rsi_atlas_evaluation.promotion import decide_promotion

# Governance docs that must exist before a component can leave fail-closed.
_GOVERNANCE_FILES: dict[SealedComponentKind, str] = {
    SealedComponentKind.EMBEDDING: "docs/dependency-governance/embedding-model-approval.md",
    SealedComponentKind.RERANKER: "docs/dependency-governance/reranker-approval.md",
    SealedComponentKind.PARSER: "docs/dependency-governance/pdf-parser-approval.md",
    SealedComponentKind.CHUNK_POLICY: "packages/ingestion/benchmarks/chunking/README.md",
}


class SealedPromotionBlocked(EvaluationError):
    """Raised when PRODUCTION claim is requested without sealed evidence."""


def default_sealed_fixture_path() -> Path:
    """Synthetic sealed-holdout fixture (machinery proof only; not owner-sealed corpus)."""
    return (
        Path(__file__).resolve().parents[4] / "fixtures" / "evaluation" / "sealed_holdout_v1.json"
    )


def _gate(gate_id: str, passed: bool, detail: str = "") -> SealedGateResult:
    return SealedGateResult(gate_id=gate_id, passed=passed, detail=detail)


def evaluate_component_gates(
    dataset: EvaluationDataset,
    *,
    component: SealedComponentKind,
    repo_root: Path,
) -> tuple[SealedGateResult, ...]:
    """Deterministic pre-promotion gates; fail-closed on any miss."""
    governance = repo_root / _GOVERNANCE_FILES[component]
    holdout = [example for example in dataset.examples if example.split is DatasetSplit.HOLDOUT]
    holdout_labels_ok = all(not example.labels for example in holdout)
    return (
        _gate(
            "dataset_frozen",
            dataset.status is DatasetStatus.FROZEN,
            f"status={dataset.status.value}",
        ),
        _gate(
            "holdout_split_present",
            len(holdout) > 0,
            f"holdout_count={len(holdout)}",
        ),
        _gate(
            "holdout_without_tuning_labels",
            holdout_labels_ok and len(holdout) > 0,
            "holdout must not carry tuning labels",
        ),
        _gate(
            "component_governance_present",
            governance.is_file(),
            str(governance.relative_to(repo_root)) if governance.is_file() else "missing",
        ),
        # Filled after eval run; placeholder for required-set completeness before merge.
        _gate("critical_deterministic_failures_zero", True, "pending_eval"),
    )


def run_sealed_promotion(
    *,
    component: SealedComponentKind,
    candidate_id: str,
    candidate_version: str,
    dataset_path: Path | None = None,
    repo_root: Path | None = None,
    created_at: datetime | None = None,
    allow_synthetic_promote: bool = False,
) -> SealedPromotionEvidence:
    """Run sealed holdout suite and emit immutable evidence.

    ``allow_synthetic_promote=True`` permits ``promote_production`` only for the
    repository synthetic fixture self-check. Owner-sealed corpora remain required
    before acceptance-matrix Proven claims.
    """
    now = created_at or datetime.now(tz=UTC)
    root = repo_root or Path(__file__).resolve().parents[4]
    path = dataset_path or default_sealed_fixture_path()
    dataset = load_dataset(path)
    content_hash = dataset_content_hash(path)
    gates = list(evaluate_component_gates(dataset, component=component, repo_root=root))

    run, decision = run_offline_evaluation(dataset, created_at=now)
    critical_ok = run.critical_failure_count == 0 and run.status is EvaluationRunStatus.COMPLETED
    # Replace pending critical gate with real result.
    gates = [
        gate
        if gate.gate_id != "critical_deterministic_failures_zero"
        else _gate(
            "critical_deterministic_failures_zero",
            critical_ok,
            f"critical_failure_count={run.critical_failure_count};status={run.status.value}",
        )
        for gate in gates
    ]
    all_passed = all(gate.passed for gate in gates)
    failed = [gate.gate_id for gate in gates if not gate.passed]

    if not all_passed:
        status = SealedPromotionStatus.FAIL_CLOSED
        outcome = PromotionOutcome.REJECT
        reasons_note = "fail_closed:" + ",".join(failed)
    elif decision.outcome is PromotionOutcome.REJECT:
        status = SealedPromotionStatus.FAIL_CLOSED
        outcome = PromotionOutcome.REJECT
        reasons_note = "evaluation_rejected"
    elif allow_synthetic_promote and path.name == "sealed_holdout_v1.json":
        # Machinery self-check: synthetic fixture may exercise promote_production path.
        # Honesty note on evidence forbids treating this as acceptance Proven.
        status = SealedPromotionStatus.PROMOTE_PRODUCTION
        outcome = PromotionOutcome.PROMOTE
        reasons_note = "synthetic_fixture_machinery_only"
    else:
        status = SealedPromotionStatus.CANDIDATE_ONLY
        outcome = PromotionOutcome.CONTINUE_SHADOW_EVALUATION
        reasons_note = "owner_sealed_corpus_required_for_production"

    # Re-decide with sealed-aware outcome when promoting.
    if status is SealedPromotionStatus.PROMOTE_PRODUCTION:
        sealed_decision = decide_promotion(run, created_at=now, sealed_promote=True)
        outcome = sealed_decision.outcome
        if outcome is not PromotionOutcome.PROMOTE:
            status = SealedPromotionStatus.FAIL_CLOSED

    return SealedPromotionEvidence(
        evidence_id=sealed_evidence_id(
            component=component,
            candidate_id=candidate_id,
            dataset_content_hash=content_hash,
            evaluation_run_id=run.run_id,
            created_at=now,
        ),
        component=component,
        candidate_id=candidate_id,
        candidate_version=candidate_version,
        dataset_id=dataset.dataset_id,
        dataset_version=dataset.version,
        dataset_content_hash=content_hash,
        evaluation_run_id=run.run_id,
        outcome=outcome,
        status=status,
        gates=tuple(gates),
        critical_failure_count=run.critical_failure_count,
        created_at=now,
        honesty_note=(
            "synthetic fixtures authorize machinery only; owner-sealed corpus required for Proven"
            if reasons_note.startswith("synthetic") or "owner_sealed" in reasons_note
            else reasons_note
        ),
    )


def require_production_authorization(evidence: SealedPromotionEvidence | None) -> None:
    """Fail closed unless sealed evidence authorizes PRODUCTION."""
    if evidence is None or not evidence.authorizes_production():
        raise SealedPromotionBlocked(
            "PRODUCTION promotion requires sealed-holdout evidence with promote_production status"
        )


def resolve_repo_root() -> Path:
    return Path(__file__).resolve().parents[4]


__all__ = [
    "SealedPromotionBlocked",
    "default_sealed_fixture_path",
    "evaluate_component_gates",
    "require_production_authorization",
    "resolve_repo_root",
    "run_sealed_promotion",
]
