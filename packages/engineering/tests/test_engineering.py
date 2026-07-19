"""Codex sanitize / approval / gate tests."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from rsi_atlas_contracts import (
    CandidatePatchStatus,
    CodexApprovalStatus,
    CodexAuthorityAction,
    CodexCommandClass,
)
from rsi_atlas_engineering import (
    AuthorityDenied,
    RedactionBlocked,
    authority_denial,
    build_candidate_patch,
    decide_approval,
    deny_authority,
    run_patch_quality_gate,
    sanitize_reproduction_bundle,
)

NOW = datetime(2026, 7, 19, 15, 30, tzinfo=UTC)


def test_sanitize_redacts_secrets() -> None:
    bundle = sanitize_reproduction_bundle(
        failure_summary="fail",
        source_versions={"engine": "0.1.0"},
        raw_inputs={"api_key": "secret-value", "query": "ok"},
        expected_behavior="pass",
        actual_behavior="fail",
        deterministic_validator_results=("schema_invalid",),
        permitted_commands=(CodexCommandClass.READ_SOURCE, CodexCommandClass.TEST),
        worktree_hint="tmp/codex-worktrees/demo",
        created_at=NOW,
    )
    assert bundle.sanitized_inputs["api_key"] == "[REDACTED]"
    assert bundle.redaction_status.value == "redacted"
    assert "api_key" in ",".join(bundle.redacted_paths)


def test_sanitize_blocks_network_command() -> None:
    with pytest.raises(RedactionBlocked):
        sanitize_reproduction_bundle(
            failure_summary="fail",
            source_versions={"engine": "0.1.0"},
            raw_inputs={},
            expected_behavior="pass",
            actual_behavior="fail",
            deterministic_validator_results=(),
            permitted_commands=(CodexCommandClass.NETWORK,),
            worktree_hint="tmp/wt",
            created_at=NOW,
        )


def test_approval_policy() -> None:
    assert decide_approval(CodexCommandClass.READ_SOURCE).status is CodexApprovalStatus.ALLOWED
    assert (
        decide_approval(CodexCommandClass.FILE_CHANGE).status
        is CodexApprovalStatus.REQUIRES_EXPLICIT_APPROVAL
    )
    assert decide_approval(CodexCommandClass.NETWORK).status is CodexApprovalStatus.DENIED


def test_merge_push_denied() -> None:
    with pytest.raises(AuthorityDenied):
        deny_authority(CodexAuthorityAction.MERGE)
    with pytest.raises(AuthorityDenied):
        deny_authority(CodexAuthorityAction.PUSH)
    record = authority_denial(CodexAuthorityAction.DEPLOY)
    assert record.denied is True


def test_quality_gate_fails_on_secret_diff() -> None:
    bundle = sanitize_reproduction_bundle(
        failure_summary="fail",
        source_versions={"engine": "0.1.0"},
        raw_inputs={"query": "ok"},
        expected_behavior="pass",
        actual_behavior="fail",
        deterministic_validator_results=(),
        permitted_commands=(CodexCommandClass.TEST,),
        worktree_hint="tmp/wt",
        created_at=NOW,
    )
    patch = build_candidate_patch(bundle, diff_text="password = 'leak'", created_at=NOW)
    gated, result = run_patch_quality_gate(patch, diff_text="password = 'leak'", created_at=NOW)
    assert gated.status is CandidatePatchStatus.GATE_FAILED
    assert gated.auto_applied is False
    assert "secret_scan" in result.blocking_failures


def test_quality_gate_passes_clean_diff() -> None:
    bundle = sanitize_reproduction_bundle(
        failure_summary="fail",
        source_versions={"engine": "0.1.0"},
        raw_inputs={"query": "ok"},
        expected_behavior="pass",
        actual_behavior="fail",
        deterministic_validator_results=(),
        permitted_commands=(CodexCommandClass.TEST,),
        worktree_hint="tmp/wt",
        created_at=NOW,
    )
    diff = "--- a/x\n+++ b/x\n+return True\n"
    patch = build_candidate_patch(bundle, diff_text=diff, created_at=NOW)
    gated, result = run_patch_quality_gate(patch, diff_text=diff, created_at=NOW)
    assert gated.status is CandidatePatchStatus.GATE_PASSED
    assert result.passed is True
    assert gated.auto_applied is False
