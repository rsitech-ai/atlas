"""Strict Phase 6 Codex engineering-plane contract tests."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from hashlib import sha256
from pathlib import Path
from stat import S_IXUSR

import pytest
import rsi_atlas_contracts as contracts
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
BASE_COMMIT = "a" * 40
OTHER_BASE_COMMIT = "d" * 40
REPOSITORY_FULL_REGRESSION_ARGV = ("./script/codex_full_regression.sh",)
REPO_ROOT = Path(__file__).resolve().parents[3]


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


def _test_evidence(
    *,
    patch_id: str,
    diff_hash: str = DIFF,
    passed: bool = True,
    exit_code: int = 0,
    started_at: datetime = NOW,
    completed_at: datetime = NOW + timedelta(seconds=2),
    stdout_bytes: int = 0,
    argv: tuple[str, ...] = REPOSITORY_FULL_REGRESSION_ARGV,
):
    suite_id = contracts.PatchTestSuite.REPOSITORY_FULL_REGRESSION
    payload = {
        "patch_id": patch_id,
        "diff_hash": diff_hash,
        "base_commit": BASE_COMMIT,
        "suite_id": suite_id,
        "argv": argv,
        "passed": passed,
        "exit_code": exit_code,
        "started_at": started_at,
        "completed_at": completed_at,
        "stdout_sha256": sha256(b"").hexdigest(),
        "stdout_bytes": stdout_bytes,
        "stderr_sha256": sha256(b"").hexdigest(),
        "stderr_bytes": 0,
        "runner_version": "rsi-atlas-trusted-runner/1.0.0",
    }
    return contracts.PatchTestEvidence(
        evidence_id=contracts.patch_test_evidence_id(**payload),
        **payload,
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


def test_candidate_patch_id_binds_expected_base_commit() -> None:
    bundle = _bundle()
    first = candidate_patch_id(
        bundle_id=bundle.bundle_id,
        diff_hash=DIFF,
        base_commit=BASE_COMMIT,
        created_at=NOW,
    )
    second = candidate_patch_id(
        bundle_id=bundle.bundle_id,
        diff_hash=DIFF,
        base_commit=OTHER_BASE_COMMIT,
        created_at=NOW,
    )

    assert first != second
    patch = CandidatePatch(
        patch_id=first,
        bundle_id=bundle.bundle_id,
        diff_hash=DIFF,
        base_commit=BASE_COMMIT,
        created_at=NOW,
    )
    assert patch.base_commit == BASE_COMMIT


def test_quality_gate_blocking_failures_must_match() -> None:
    bundle = _bundle()
    patch_id = candidate_patch_id(bundle_id=bundle.bundle_id, diff_hash=DIFF, created_at=NOW)
    gate_id = patch_gate_id(patch_id=patch_id, created_at=NOW)
    result = PatchQualityGateResult(
        gate_id=gate_id,
        patch_id=patch_id,
        diff_hash=DIFF,
        base_commit=None,
        checks=(
            PatchQualityCheck(name="secret_scan", passed=True),
            PatchQualityCheck(name="unit_test_evidence", passed=False, detail="failed"),
        ),
        passed=False,
        blocking_failures=("unit_test_evidence",),
        created_at=NOW,
    )
    assert result.passed is False
    with pytest.raises(ValidationError, match="blocking_failures"):
        PatchQualityGateResult(
            gate_id=gate_id,
            patch_id=patch_id,
            diff_hash=DIFF,
            base_commit=None,
            checks=(PatchQualityCheck(name="unit_test_evidence", passed=False, detail="failed"),),
            passed=False,
            blocking_failures=("secret_scan",),
            created_at=NOW,
        )


def test_patch_test_evidence_accepts_exact_allowlisted_suite_command() -> None:
    bundle = _bundle()
    patch_id = candidate_patch_id(bundle_id=bundle.bundle_id, diff_hash=DIFF, created_at=NOW)

    evidence = _test_evidence(patch_id=patch_id)

    assert evidence.patch_id == patch_id
    assert evidence.base_commit == BASE_COMMIT
    assert evidence.suite_id is contracts.PatchTestSuite.REPOSITORY_FULL_REGRESSION
    assert evidence.argv == REPOSITORY_FULL_REGRESSION_ARGV


def test_repository_full_regression_script_covers_repository_gate_without_authority() -> None:
    script = REPO_ROOT / "script" / "codex_full_regression.sh"
    source = script.read_text(encoding="utf-8")

    assert script.stat().st_mode & S_IXUSR
    for command in (
        "uv lock --check",
        "uv run ruff check packages services infra script tests",
        "uv run ruff format --check packages services infra script tests",
        "uv run mypy packages services infra",
        "uv run python script/audit_pdf_parser_dependencies.py verify",
        'RSI_ATLAS_TEST_DATABASE_URL="$(./infra/local/postgres.sh test-url)" uv run pytest -q',
        "swift test --package-path apps/macos",
        "swift build --package-path apps/macos --product RSIAtlas",
    ):
        assert command in source
    assert "packages/contracts/tests/test_codex.py" not in source
    assert "does not authorize merge or push" in source


def test_patch_test_evidence_id_binds_base_commit_and_execution_payload() -> None:
    bundle = _bundle()
    patch_id = candidate_patch_id(bundle_id=bundle.bundle_id, diff_hash=DIFF, created_at=NOW)
    evidence = _test_evidence(patch_id=patch_id)
    payload = evidence.model_dump(mode="python")

    payload["base_commit"] = "d" * 40
    with pytest.raises(ValidationError, match="evidence_id"):
        contracts.PatchTestEvidence(**payload)


def test_patch_test_evidence_requires_full_lowercase_base_commit() -> None:
    bundle = _bundle()
    patch_id = candidate_patch_id(bundle_id=bundle.bundle_id, diff_hash=DIFF, created_at=NOW)
    evidence = _test_evidence(patch_id=patch_id)
    payload = evidence.model_dump(mode="python")

    payload["base_commit"] = "ABC123"
    with pytest.raises(ValidationError):
        contracts.PatchTestEvidence(**payload)


def test_patch_test_evidence_rejects_unknown_suite_and_wrong_argv() -> None:
    bundle = _bundle()
    patch_id = candidate_patch_id(bundle_id=bundle.bundle_id, diff_hash=DIFF, created_at=NOW)

    with pytest.raises(ValidationError):
        _test_evidence(patch_id=patch_id, argv=("pytest", "-q"))
    with pytest.raises(ValidationError):
        contracts.PatchTestEvidence(
            evidence_id="patchtestevidence:" + "c" * 64,
            patch_id=patch_id,
            diff_hash=DIFF,
            base_commit=BASE_COMMIT,
            suite_id="caller_chosen_suite",
            argv=REPOSITORY_FULL_REGRESSION_ARGV,
            passed=True,
            exit_code=0,
            started_at=NOW,
            completed_at=NOW + timedelta(seconds=2),
            stdout_sha256=sha256(b"").hexdigest(),
            stdout_bytes=0,
            stderr_sha256=sha256(b"").hexdigest(),
            stderr_bytes=0,
            runner_version="rsi-atlas-trusted-runner/1.0.0",
        )


def test_patch_test_evidence_rejects_inconsistent_exit_semantics() -> None:
    bundle = _bundle()
    patch_id = candidate_patch_id(bundle_id=bundle.bundle_id, diff_hash=DIFF, created_at=NOW)

    with pytest.raises(ValidationError, match="exit code"):
        _test_evidence(patch_id=patch_id, passed=True, exit_code=1)


def test_patch_test_evidence_requires_utc_ordered_bounded_timestamps() -> None:
    bundle = _bundle()
    patch_id = candidate_patch_id(bundle_id=bundle.bundle_id, diff_hash=DIFF, created_at=NOW)

    with pytest.raises(ValidationError, match="UTC"):
        _test_evidence(patch_id=patch_id, started_at=NOW.replace(tzinfo=None))
    with pytest.raises(ValidationError, match="completed_at"):
        _test_evidence(
            patch_id=patch_id,
            started_at=NOW + timedelta(seconds=3),
            completed_at=NOW + timedelta(seconds=2),
        )


def test_patch_test_evidence_rejects_oversized_captured_output() -> None:
    bundle = _bundle()
    patch_id = candidate_patch_id(bundle_id=bundle.bundle_id, diff_hash=DIFF, created_at=NOW)

    with pytest.raises(ValidationError):
        _test_evidence(patch_id=patch_id, stdout_bytes=1_048_577)


def test_passed_gate_requires_matching_successful_evidence_in_audit_result() -> None:
    bundle = _bundle()
    patch_id = candidate_patch_id(bundle_id=bundle.bundle_id, diff_hash=DIFF, created_at=NOW)
    evidence = _test_evidence(patch_id=patch_id)
    check = PatchQualityCheck(name="unit_test_evidence", passed=True)

    with pytest.raises(ValidationError, match="test evidence"):
        PatchQualityGateResult(
            gate_id=patch_gate_id(patch_id=patch_id, created_at=NOW),
            patch_id=patch_id,
            diff_hash=DIFF,
            base_commit=BASE_COMMIT,
            checks=(check,),
            passed=True,
            created_at=NOW,
        )
    with pytest.raises(ValidationError, match="test evidence"):
        PatchQualityGateResult(
            gate_id=patch_gate_id(patch_id=patch_id, created_at=NOW),
            patch_id=patch_id,
            diff_hash="d" * 64,
            base_commit=BASE_COMMIT,
            checks=(check,),
            passed=True,
            test_evidence=(evidence,),
            created_at=NOW,
        )
    with pytest.raises(ValidationError, match="test evidence"):
        PatchQualityGateResult(
            gate_id=patch_gate_id(patch_id=patch_id, created_at=NOW),
            patch_id=patch_id,
            diff_hash=DIFF,
            base_commit=OTHER_BASE_COMMIT,
            checks=(check,),
            passed=True,
            test_evidence=(evidence,),
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
