"""Fail-closed sealed-holdout promotion for §35 selection-by-evaluation components."""

from __future__ import annotations

import json
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

# Governance docs that must exist before a component can leave fail-closed.
_GOVERNANCE_FILES: dict[SealedComponentKind, str] = {
    SealedComponentKind.EMBEDDING: "docs/dependency-governance/embedding-model-approval.md",
    SealedComponentKind.RERANKER: "docs/dependency-governance/reranker-approval.md",
    SealedComponentKind.PARSER: "docs/dependency-governance/pdf-parser-approval.md",
    SealedComponentKind.CHUNK_POLICY: "packages/ingestion/benchmarks/chunking/README.md",
}

_SYNTHETIC_FIXTURE_NAMES = frozenset({"sealed_holdout_v1.json"})


class SealedPromotionBlocked(EvaluationError):
    """Raised when PRODUCTION claim is requested without sealed evidence."""


def default_sealed_fixture_path() -> Path:
    """Synthetic sealed-holdout fixture (machinery / development package only)."""
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

    ``allow_synthetic_promote=True`` permits a **development sealed package** status
    for repository synthetic fixtures only. It never authorizes PRODUCTION Proven.
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
    elif allow_synthetic_promote and path.name in _SYNTHETIC_FIXTURE_NAMES:
        # Development sealed package: exercises the offline package path honestly.
        status = SealedPromotionStatus.DEVELOPMENT_SEALED_PACKAGE
        outcome = PromotionOutcome.CONTINUE_SHADOW_EVALUATION
        reasons_note = "development_sealed_package_synthetic_fixture"
    else:
        status = SealedPromotionStatus.CANDIDATE_ONLY
        outcome = PromotionOutcome.CONTINUE_SHADOW_EVALUATION
        reasons_note = "owner_sealed_corpus_required_for_production"

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
            "development sealed package only; owner-sealed corpus required for Section 33 Proven"
            if status is SealedPromotionStatus.DEVELOPMENT_SEALED_PACKAGE
            or "owner_sealed" in reasons_note
            else reasons_note
        ),
    )


def write_development_sealed_package(
    *,
    out_dir: Path,
    repo_root: Path | None = None,
    created_at: datetime | None = None,
) -> Path:
    """Write an offline development sealed package for all §35 components.

    Label is ``development_sealed_package`` — never PRODUCTION Proven.
    """
    now = created_at or datetime.now(tz=UTC)
    root = repo_root or resolve_repo_root()
    package_dir = out_dir / f"development_sealed_package_{now.strftime('%Y%m%dT%H%M%SZ')}"
    package_dir.mkdir(parents=True, exist_ok=True)
    candidates = {
        SealedComponentKind.EMBEDDING: ("oss_token_hash_v1", "1.0.0"),
        SealedComponentKind.RERANKER: ("lexical_overlap_rerank_v1", "1.0.0"),
        SealedComponentKind.PARSER: ("tier0_pypdf", "1.0.0"),
        SealedComponentKind.CHUNK_POLICY: ("fixed_token", "1.0.0"),
    }
    manifest: dict[str, object] = {
        "package_label": "development_sealed_package",
        "schema_version": "rsi-atlas.development-sealed-package.v1",
        "created_at": now.isoformat().replace("+00:00", "Z"),
        "authorizes_production": False,
        "honesty_note": (
            "Synthetic fixture package for offline promotion E2E; "
            "does not authorize Section 33 PRODUCTION Proven"
        ),
        "components": [],
    }
    components_out: list[dict[str, object]] = []
    for component, (candidate_id, version) in candidates.items():
        evidence = run_sealed_promotion(
            component=component,
            candidate_id=candidate_id,
            candidate_version=version,
            repo_root=root,
            created_at=now,
            allow_synthetic_promote=True,
        )
        if not evidence.is_development_sealed_package():
            raise SealedPromotionBlocked(
                f"development package incomplete for {component.value}: {evidence.status.value}"
            )
        evidence_path = package_dir / f"{component.value}_evidence.json"
        evidence_path.write_bytes(evidence.model_dump_json(indent=2).encode("utf-8"))
        components_out.append(
            {
                "component": component.value,
                "candidate_id": candidate_id,
                "status": evidence.status.value,
                "evidence_id": evidence.evidence_id,
                "evidence_file": evidence_path.name,
                "authorizes_production": evidence.authorizes_production(),
            }
        )
    manifest["components"] = components_out
    manifest_path = package_dir / "MANIFEST.json"
    payload = json.dumps(manifest, indent=2, sort_keys=True) + "\n"
    manifest_path.write_text(payload, encoding="utf-8")
    return package_dir


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
    "write_development_sealed_package",
]
