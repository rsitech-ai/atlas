"""Codex sanitize / approval / gate tests."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from hashlib import sha256

import pytest
import rsi_atlas_contracts as contracts
from rsi_atlas_contracts import (
    CandidatePatch,
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
BASE_COMMIT = "a" * 40
OTHER_BASE_COMMIT = "d" * 40
REPOSITORY_FULL_REGRESSION_ARGV = ("./script/codex_full_regression.sh",)


def _bundle():
    return sanitize_reproduction_bundle(
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


def _evidence(
    patch: CandidatePatch,
    *,
    patch_id: str | None = None,
    diff_hash: str | None = None,
    base_commit: str | None = None,
    passed: bool = True,
    exit_code: int = 0,
    started_at: datetime = NOW,
    completed_at: datetime = NOW + timedelta(seconds=2),
):
    payload = {
        "patch_id": patch_id or patch.patch_id,
        "diff_hash": diff_hash or patch.diff_hash,
        "base_commit": base_commit or patch.base_commit,
        "suite_id": contracts.PatchTestSuite.REPOSITORY_FULL_REGRESSION,
        "argv": REPOSITORY_FULL_REGRESSION_ARGV,
        "passed": passed,
        "exit_code": exit_code,
        "started_at": started_at,
        "completed_at": completed_at,
        "stdout_sha256": sha256(b"").hexdigest(),
        "stdout_bytes": 0,
        "stderr_sha256": sha256(b"").hexdigest(),
        "stderr_bytes": 0,
        "runner_version": "rsi-atlas-trusted-runner/1.0.0",
    }
    return contracts.PatchTestEvidence(
        evidence_id=contracts.patch_test_evidence_id(**payload),
        **payload,
    )


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


def test_quality_gate_fails_clean_diff_without_test_evidence() -> None:
    bundle = _bundle()
    diff = "--- a/x\n+++ b/x\n+return True\n"
    patch = build_candidate_patch(bundle, diff_text=diff, created_at=NOW)
    gated, result = run_patch_quality_gate(patch, diff_text=diff, created_at=NOW)

    assert gated.status is CandidatePatchStatus.GATE_FAILED
    assert result.passed is False
    assert result.base_commit is None
    assert "base_commit_match" in result.blocking_failures
    assert "trusted_worktree_base" in result.blocking_failures
    assert "unit_test_evidence" in result.blocking_failures
    assert result.test_evidence == ()
    assert gated.auto_applied is False


def test_quality_gate_accepts_evidence_components_but_requires_trusted_worktree_base() -> None:
    diff = "--- a/x\n+++ b/x\n+return True\n"
    patch = build_candidate_patch(
        _bundle(), diff_text=diff, base_commit=BASE_COMMIT, created_at=NOW
    )
    evidence = _evidence(patch)

    gated, result = run_patch_quality_gate(
        patch,
        diff_text=diff,
        created_at=NOW + timedelta(seconds=3),
        test_evidence=(evidence,),
    )

    checks = {check.name: check.passed for check in result.checks}
    assert gated.status is CandidatePatchStatus.GATE_FAILED
    assert result.passed is False
    assert result.diff_hash == patch.diff_hash
    assert result.base_commit == BASE_COMMIT
    assert result.test_evidence == (evidence,)
    assert checks["unit_test_evidence"] is True
    assert checks["base_commit_match"] is True
    assert checks["trusted_worktree_base"] is False
    assert result.blocking_failures == ("trusted_worktree_base",)


def test_quality_gate_rejects_nonzero_test_evidence() -> None:
    diff = "--- a/x\n+++ b/x\n+return True\n"
    patch = build_candidate_patch(
        _bundle(), diff_text=diff, base_commit=BASE_COMMIT, created_at=NOW
    )
    evidence = _evidence(patch, passed=False, exit_code=1)

    gated, result = run_patch_quality_gate(
        patch,
        diff_text=diff,
        created_at=NOW + timedelta(seconds=3),
        test_evidence=(evidence,),
    )

    assert gated.status is CandidatePatchStatus.GATE_FAILED
    assert "unit_test_evidence" in result.blocking_failures


@pytest.mark.parametrize(
    ("evidence_patch_id", "evidence_diff_hash"),
    [
        ("candidatepatch:" + "f" * 64, None),
        (None, "c" * 64),
    ],
)
def test_quality_gate_rejects_evidence_for_another_patch_or_diff(
    evidence_patch_id: str | None,
    evidence_diff_hash: str | None,
) -> None:
    diff = "--- a/x\n+++ b/x\n+return True\n"
    patch = build_candidate_patch(
        _bundle(), diff_text=diff, base_commit=BASE_COMMIT, created_at=NOW
    )
    evidence = _evidence(
        patch,
        patch_id=evidence_patch_id,
        diff_hash=evidence_diff_hash,
    )

    gated, result = run_patch_quality_gate(
        patch,
        diff_text=diff,
        created_at=NOW + timedelta(seconds=3),
        test_evidence=(evidence,),
    )

    assert gated.status is CandidatePatchStatus.GATE_FAILED
    assert "unit_test_evidence" in result.blocking_failures


def test_quality_gate_rejects_stale_test_evidence() -> None:
    diff = "--- a/x\n+++ b/x\n+return True\n"
    patch = build_candidate_patch(
        _bundle(), diff_text=diff, base_commit=BASE_COMMIT, created_at=NOW
    )
    evidence = _evidence(patch)

    gated, result = run_patch_quality_gate(
        patch,
        diff_text=diff,
        created_at=NOW + timedelta(minutes=15, seconds=3),
        test_evidence=(evidence,),
    )

    assert gated.status is CandidatePatchStatus.GATE_FAILED
    assert "unit_test_evidence" in result.blocking_failures


def test_quality_gate_recomputes_diff_hash_instead_of_trusting_patch_metadata() -> None:
    diff = "--- a/x\n+++ b/x\n+return True\n"
    patch = build_candidate_patch(
        _bundle(), diff_text=diff, base_commit=BASE_COMMIT, created_at=NOW
    )
    evidence = _evidence(patch)

    gated, result = run_patch_quality_gate(
        patch,
        diff_text=diff + "+tampered = True\n",
        created_at=NOW + timedelta(seconds=3),
        test_evidence=(evidence,),
    )

    assert gated.status is CandidatePatchStatus.GATE_FAILED
    assert "diff_hash_match" in result.blocking_failures
    assert "unit_test_evidence" in result.blocking_failures


def test_quality_gate_rejects_evidence_from_another_candidate_base() -> None:
    diff = "--- a/x\n+++ b/x\n+return True\n"
    bundle = _bundle()
    first = build_candidate_patch(bundle, diff_text=diff, base_commit=BASE_COMMIT, created_at=NOW)
    second = build_candidate_patch(
        bundle, diff_text=diff, base_commit=OTHER_BASE_COMMIT, created_at=NOW
    )
    evidence = _evidence(first)

    assert first.patch_id != second.patch_id
    gated, result = run_patch_quality_gate(
        second,
        diff_text=diff,
        created_at=NOW + timedelta(seconds=3),
        test_evidence=(evidence,),
    )

    assert gated.status is CandidatePatchStatus.GATE_FAILED
    assert "base_commit_match" in result.blocking_failures
    assert "unit_test_evidence" in result.blocking_failures
