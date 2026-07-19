"""Strict Phase 6 Codex engineering-plane contract tests."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError
from rsi_atlas_contracts.codex import (
    BLOCKED_CODEX_AUTHORITY,
    CandidatePatch,
    CandidatePatchStatus,
    CodexApprovalDecision,
    CodexApprovalStatus,
    CodexAuthorityAction,
    CodexAuthorityDenial,
    CodexCommandClass,
    PatchQualityCheck,
    PatchQualityGateResult,
    RedactionStatus,
    SanitizedReproductionBundle,
    candidate_patch_id,
    patch_gate_id,
    reproduction_bundle_id,
)

NOW = datetime(2026, 7, 19, 15, 0, tzinfo=UTC)
DIFF = "b" * 64


def _bundle() -> SanitizedReproductionBundle:
    bundle_id = reproduction_bundle_id(
        failure_summary="schema regression", diff_seed="seed", created_at=NOW
    )
    return SanitizedReproductionBundle(
        bundle_id=bundle_id,
        failure_summary="schema regression",
        source_versions={"engine": "0.1.0"},
        sanitized_inputs={"trace_span": "atlas.validate"},
        expected_behavior="pass schema",
        actual_behavior="schema_invalid",
        deterministic_validator_results=("schema_invalid",),
        permitted_commands=(CodexCommandClass.READ_SOURCE, CodexCommandClass.TEST),
        redaction_status=RedactionStatus.CLEAN,
        worktree_hint="tmp/codex-worktrees/demo",
        created_at=NOW,
    )


def test_all_authority_actions_blocked() -> None:
    assert CodexAuthorityAction.MERGE in BLOCKED_CODEX_AUTHORITY
    assert CodexAuthorityAction.PUSH in BLOCKED_CODEX_AUTHORITY
    denial = CodexAuthorityDenial(action=CodexAuthorityAction.MERGE, reason="no automatic merge")
    assert denial.denied is True
    with pytest.raises(ValidationError, match="always denied"):
        CodexAuthorityDenial(action=CodexAuthorityAction.PUSH, denied=False, reason="nope")


def test_bundle_requires_network_and_credential_denial() -> None:
    with pytest.raises(ValidationError, match="network"):
        SanitizedReproductionBundle(
            bundle_id=reproduction_bundle_id(failure_summary="x", diff_seed="s", created_at=NOW),
            failure_summary="x",
            source_versions={"engine": "0.1.0"},
            sanitized_inputs={},
            expected_behavior="a",
            actual_behavior="b",
            permitted_commands=(CodexCommandClass.READ_SOURCE,),
            redaction_status=RedactionStatus.CLEAN,
            worktree_hint="tmp/wt",
            network_denied=False,
            created_at=NOW,
        )


def test_network_command_never_permitted() -> None:
    with pytest.raises(ValidationError, match="network"):
        SanitizedReproductionBundle(
            bundle_id=reproduction_bundle_id(failure_summary="x", diff_seed="s", created_at=NOW),
            failure_summary="x",
            source_versions={"engine": "0.1.0"},
            sanitized_inputs={},
            expected_behavior="a",
            actual_behavior="b",
            permitted_commands=(CodexCommandClass.NETWORK,),
            redaction_status=RedactionStatus.CLEAN,
            worktree_hint="tmp/wt",
            created_at=NOW,
        )


def test_candidate_patch_cannot_auto_apply() -> None:
    bundle = _bundle()
    patch_id = candidate_patch_id(bundle_id=bundle.bundle_id, diff_hash=DIFF, created_at=NOW)
    with pytest.raises(ValidationError, match="auto-applied"):
        CandidatePatch(
            patch_id=patch_id,
            bundle_id=bundle.bundle_id,
            diff_hash=DIFF,
            status=CandidatePatchStatus.CANDIDATE,
            auto_applied=True,
            created_at=NOW,
        )


def test_quality_gate_blocking_failures_must_match() -> None:
    bundle = _bundle()
    patch_id = candidate_patch_id(bundle_id=bundle.bundle_id, diff_hash=DIFF, created_at=NOW)
    gate_id = patch_gate_id(patch_id=patch_id, created_at=NOW)
    result = PatchQualityGateResult(
        gate_id=gate_id,
        patch_id=patch_id,
        checks=(
            PatchQualityCheck(name="secret_scan", passed=True),
            PatchQualityCheck(name="unit_stub", passed=False, detail="failed"),
        ),
        passed=False,
        blocking_failures=("unit_stub",),
        created_at=NOW,
    )
    assert result.passed is False
    with pytest.raises(ValidationError, match="blocking_failures"):
        PatchQualityGateResult(
            gate_id=gate_id,
            patch_id=patch_id,
            checks=(PatchQualityCheck(name="unit_stub", passed=False, detail="failed"),),
            passed=False,
            blocking_failures=("secret_scan",),
            created_at=NOW,
        )


def test_approval_network_denied() -> None:
    decision = CodexApprovalDecision(
        command_class=CodexCommandClass.NETWORK,
        status=CodexApprovalStatus.DENIED,
        reason="strict mode",
    )
    assert decision.status is CodexApprovalStatus.DENIED
    with pytest.raises(ValidationError, match="denied"):
        CodexApprovalDecision(
            command_class=CodexCommandClass.NETWORK,
            status=CodexApprovalStatus.ALLOWED,
            reason="nope",
        )
