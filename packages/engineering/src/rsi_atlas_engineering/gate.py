"""Fail-closed Codex candidate patch quality gate."""

from __future__ import annotations

import re
from datetime import datetime, timedelta
from hashlib import sha256

from rsi_atlas_contracts import (
    CandidatePatch,
    CandidatePatchStatus,
    PatchQualityCheck,
    PatchQualityGateResult,
    PatchTestEvidence,
    SanitizedReproductionBundle,
    candidate_patch_id,
    patch_gate_id,
)

MAX_TEST_EVIDENCE_AGE = timedelta(minutes=15)

_SECRET_IN_DIFF = re.compile(
    r"(password\s*=|api[_-]?key|BEGIN PRIVATE KEY|sk-live-|AKIA)",
    re.IGNORECASE,
)


def build_candidate_patch(
    bundle: SanitizedReproductionBundle,
    *,
    diff_text: str,
    created_at: datetime,
) -> CandidatePatch:
    diff_hash = sha256(diff_text.encode("utf-8")).hexdigest()
    return CandidatePatch(
        patch_id=candidate_patch_id(
            bundle_id=bundle.bundle_id, diff_hash=diff_hash, created_at=created_at
        ),
        bundle_id=bundle.bundle_id,
        diff_hash=diff_hash,
        status=CandidatePatchStatus.CANDIDATE,
        auto_applied=False,
        created_at=created_at,
    )


def run_patch_quality_gate(
    patch: CandidatePatch,
    *,
    diff_text: str,
    created_at: datetime,
    test_evidence: tuple[PatchTestEvidence, ...] = (),
) -> tuple[CandidatePatch, PatchQualityGateResult]:
    """Run deterministic checks; never auto-apply the patch."""
    observed_diff_hash = sha256(diff_text.encode("utf-8")).hexdigest()
    diff_hash_matches = observed_diff_hash == patch.diff_hash
    evidence_matches = bool(test_evidence) and all(
        evidence.patch_id == patch.patch_id
        and evidence.diff_hash == patch.diff_hash
        and evidence.diff_hash == observed_diff_hash
        and evidence.passed
        and evidence.exit_code == 0
        and evidence.started_at >= patch.created_at
        and evidence.completed_at <= created_at
        and created_at - evidence.completed_at <= MAX_TEST_EVIDENCE_AGE
        for evidence in test_evidence
    )
    checks = [
        PatchQualityCheck(
            name="schema_shape",
            passed=bool(patch.patch_id.startswith("candidatepatch:")),
            detail="patch id shape",
        ),
        PatchQualityCheck(
            name="diff_hash_match",
            passed=diff_hash_matches,
            detail="submitted diff sha256 matches candidate patch",
        ),
        PatchQualityCheck(
            name="secret_scan",
            passed=_SECRET_IN_DIFF.search(diff_text) is None,
            detail="diff secret scan",
        ),
        PatchQualityCheck(
            name="unit_test_evidence",
            passed=evidence_matches,
            detail="trusted diff-bound test evidence",
        ),
        PatchQualityCheck(
            name="no_auto_apply",
            passed=patch.auto_applied is False,
            detail="candidate must remain unapplied",
        ),
    ]
    failed = tuple(check.name for check in checks if not check.passed)
    passed = not failed
    status = CandidatePatchStatus.GATE_PASSED if passed else CandidatePatchStatus.GATE_FAILED
    gated = CandidatePatch(
        patch_id=patch.patch_id,
        bundle_id=patch.bundle_id,
        diff_hash=patch.diff_hash,
        status=status,
        auto_applied=False,
        created_at=patch.created_at,
    )
    result = PatchQualityGateResult(
        gate_id=patch_gate_id(patch_id=patch.patch_id, created_at=created_at),
        patch_id=patch.patch_id,
        diff_hash=observed_diff_hash,
        checks=tuple(checks),
        passed=passed,
        blocking_failures=failed,
        test_evidence=test_evidence,
        created_at=created_at,
    )
    return gated, result
