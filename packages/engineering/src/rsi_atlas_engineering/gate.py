"""Fail-closed Codex candidate patch quality gate."""

from __future__ import annotations

import re
from datetime import datetime
from hashlib import sha256

from rsi_atlas_contracts import (
    CandidatePatch,
    CandidatePatchStatus,
    PatchQualityCheck,
    PatchQualityGateResult,
    SanitizedReproductionBundle,
    candidate_patch_id,
    patch_gate_id,
)

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
    unit_stub_passed: bool = True,
) -> tuple[CandidatePatch, PatchQualityGateResult]:
    """Run deterministic checks; never auto-apply the patch."""
    checks = [
        PatchQualityCheck(
            name="schema_shape",
            passed=bool(patch.patch_id.startswith("candidatepatch:")),
            detail="patch id shape",
        ),
        PatchQualityCheck(
            name="secret_scan",
            passed=_SECRET_IN_DIFF.search(diff_text) is None,
            detail="diff secret scan",
        ),
        PatchQualityCheck(
            name="unit_stub",
            passed=unit_stub_passed,
            detail="development unit-test stub hook",
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
        checks=tuple(checks),
        passed=passed,
        blocking_failures=failed,
        created_at=created_at,
    )
    return gated, result
