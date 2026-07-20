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
    base_commit: str | None = None,
) -> CandidatePatch:
    diff_hash = sha256(diff_text.encode("utf-8")).hexdigest()
    return CandidatePatch(
        patch_id=candidate_patch_id(
            bundle_id=bundle.bundle_id,
            diff_hash=diff_hash,
            base_commit=base_commit,
            created_at=created_at,
        ),
        bundle_id=bundle.bundle_id,
        diff_hash=diff_hash,
        base_commit=base_commit,
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
    """Run deterministic checks; a gate result never authorizes merge or push."""
    observed_diff_hash = sha256(diff_text.encode("utf-8")).hexdigest()
    diff_hash_matches = observed_diff_hash == patch.diff_hash
    base_commit_matches = (
        patch.base_commit is not None
        and bool(test_evidence)
        and all(evidence.base_commit == patch.base_commit for evidence in test_evidence)
    )
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
    trusted_worktree_base = False
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
            name="base_commit_match",
            passed=base_commit_matches,
            detail="evidence base commit matches the candidate expectation",
        ),
        PatchQualityCheck(
            name="secret_scan",
            passed=_SECRET_IN_DIFF.search(diff_text) is None,
            detail="diff secret scan",
        ),
        PatchQualityCheck(
            name="unit_test_evidence",
            passed=evidence_matches,
            detail="repository-full diff-bound test evidence",
        ),
        PatchQualityCheck(
            name="trusted_worktree_base",
            passed=trusted_worktree_base,
            detail="trusted worktree base resolver is not integrated",
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
        base_commit=patch.base_commit,
        status=status,
        auto_applied=False,
        created_at=patch.created_at,
    )
    result = PatchQualityGateResult(
        gate_id=patch_gate_id(patch_id=patch.patch_id, created_at=created_at),
        patch_id=patch.patch_id,
        diff_hash=observed_diff_hash,
        base_commit=patch.base_commit,
        checks=tuple(checks),
        passed=passed,
        blocking_failures=failed,
        test_evidence=test_evidence,
        created_at=created_at,
    )
    return gated, result
