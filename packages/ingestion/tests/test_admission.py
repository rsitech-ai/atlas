from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

import pytest
from rsi_atlas_contracts import (
    AcquisitionMethod,
    AcquisitionRequest,
    AdmissionOutcome,
    ArtifactID,
    DocumentLifecycle,
    NetworkProfile,
    PDFSafetyProfile,
    SafetyCheckState,
)
from rsi_atlas_ingestion import PDFAdmissionDecision, PDFAdmissionPolicy


def _request() -> AcquisitionRequest:
    acquisition_id = uuid4()
    return AcquisitionRequest(
        acquisition_id=acquisition_id,
        method=AcquisitionMethod.MANUAL_CLI,
        original_filename="evidence.pdf",
        source_locator=f"manual-import:{acquisition_id}",
        declared_media_type="application/pdf",
        collector_version="atlas-cli-0.1.0",
        network_profile=NetworkProfile.OFFLINE,
    )


def _profile(**changes: Any) -> PDFSafetyProfile:
    digest = "a" * 64
    values: dict[str, Any] = {
        "artifact_id": ArtifactID(f"sha256:{digest}"),
        "digest": digest,
        "size_bytes": 512,
        "header_version": "1.7",
        "eof_marker_present": True,
        "page_marker_count": 1,
        "mime_signature_consistency": SafetyCheckState.PASS,
        "size_limit": SafetyCheckState.PASS,
        "page_count_limit": SafetyCheckState.PASS,
        "encryption_password_state": SafetyCheckState.PASS,
        "malformed_structure": SafetyCheckState.PASS,
        "embedded_files": SafetyCheckState.PASS,
        "active_actions": SafetyCheckState.PASS,
        "suspicious_references": SafetyCheckState.PASS,
        "decompression_ratio": SafetyCheckState.PASS,
        "source_policy": SafetyCheckState.PASS,
        "available_disk": SafetyCheckState.PASS,
        "inspected_at": datetime(2026, 7, 18, 20, 45, tzinfo=UTC),
    }
    values.update(changes)
    return PDFSafetyProfile(**values)


def _evaluate(
    *, profile: PDFSafetyProfile | None = None, duplicate_of: UUID | None = None
) -> PDFAdmissionDecision:
    return PDFAdmissionPolicy().evaluate(
        profile=profile or _profile(),
        request=_request(),
        duplicate_of_acquisition_id=duplicate_of,
    )


def test_exact_duplicate_precedes_other_policy_outcomes() -> None:
    duplicate_id = UUID("77777777-7777-4777-8777-777777777777")

    decision = _evaluate(
        profile=_profile(
            mime_signature_consistency=SafetyCheckState.FAIL,
            active_actions=SafetyCheckState.FAIL,
        ),
        duplicate_of=duplicate_id,
    )

    assert decision == PDFAdmissionDecision(
        lifecycle=DocumentLifecycle.DUPLICATE,
        outcome=AdmissionOutcome.MARK_EXACT_DUPLICATE,
        reason_codes=("exact_duplicate",),
        duplicate_of_acquisition_id=duplicate_id,
    )


@pytest.mark.parametrize(
    ("field", "outcome", "reason"),
    (
        (
            "mime_signature_consistency",
            AdmissionOutcome.REJECT_UNSAFE,
            "pdf_signature_or_mime_invalid",
        ),
        ("size_limit", AdmissionOutcome.REJECT_POLICY_VIOLATION, "size_limit_exceeded"),
        ("source_policy", AdmissionOutcome.REJECT_POLICY_VIOLATION, "source_policy_denied"),
        ("encryption_password_state", AdmissionOutcome.REQUEST_PASSWORD, "password_required"),
        ("malformed_structure", AdmissionOutcome.QUARANTINE_FOR_REVIEW, "malformed_structure"),
        ("embedded_files", AdmissionOutcome.QUARANTINE_FOR_REVIEW, "embedded_files_detected"),
        ("active_actions", AdmissionOutcome.QUARANTINE_FOR_REVIEW, "active_actions_detected"),
        (
            "suspicious_references",
            AdmissionOutcome.QUARANTINE_FOR_REVIEW,
            "suspicious_references_detected",
        ),
        (
            "decompression_ratio",
            AdmissionOutcome.QUARANTINE_FOR_REVIEW,
            "decompression_ratio_unsafe",
        ),
        ("page_count_limit", AdmissionOutcome.QUARANTINE_FOR_REVIEW, "page_limit_unresolved"),
        ("available_disk", AdmissionOutcome.QUARANTINE_FOR_REVIEW, "available_disk_insufficient"),
    ),
)
def test_failed_check_maps_to_exact_fail_closed_outcome(
    field: str, outcome: AdmissionOutcome, reason: str
) -> None:
    decision = _evaluate(profile=_profile(**{field: SafetyCheckState.FAIL}))

    assert decision.outcome is outcome
    assert reason in decision.reason_codes


@pytest.mark.parametrize(
    "field",
    (
        "mime_signature_consistency",
        "size_limit",
        "page_count_limit",
        "encryption_password_state",
        "malformed_structure",
        "embedded_files",
        "active_actions",
        "suspicious_references",
        "decompression_ratio",
        "source_policy",
        "available_disk",
    ),
)
def test_any_unknown_mandatory_check_requires_review(field: str) -> None:
    decision = _evaluate(profile=_profile(**{field: SafetyCheckState.UNKNOWN}))

    assert decision.lifecycle is DocumentLifecycle.AWAITING_REVIEW
    assert decision.outcome is AdmissionOutcome.QUARANTINE_FOR_REVIEW
    assert decision.reason_codes == ("required_check_unknown",)


def test_all_pass_profile_still_cannot_be_admitted_without_a_promoted_profiler() -> None:
    decision = _evaluate()

    assert decision.lifecycle is DocumentLifecycle.AWAITING_REVIEW
    assert decision.outcome is AdmissionOutcome.QUARANTINE_FOR_REVIEW
    assert decision.reason_codes == ("isolated_profiler_not_promoted",)
    assert decision.duplicate_of_acquisition_id is None


def test_multiple_failed_review_checks_produce_sorted_unique_reasons() -> None:
    decision = _evaluate(
        profile=_profile(
            active_actions=SafetyCheckState.FAIL,
            embedded_files=SafetyCheckState.FAIL,
            suspicious_references=SafetyCheckState.FAIL,
        )
    )

    assert decision.reason_codes == (
        "active_actions_detected",
        "embedded_files_detected",
        "suspicious_references_detected",
    )


def test_rejection_priority_is_deterministic() -> None:
    decision = _evaluate(
        profile=_profile(
            mime_signature_consistency=SafetyCheckState.FAIL,
            size_limit=SafetyCheckState.FAIL,
            encryption_password_state=SafetyCheckState.FAIL,
            active_actions=SafetyCheckState.FAIL,
        )
    )

    assert decision.lifecycle is DocumentLifecycle.REJECTED
    assert decision.outcome is AdmissionOutcome.REJECT_UNSAFE
    assert decision.reason_codes == ("pdf_signature_or_mime_invalid",)


def test_policy_is_pure_and_deterministic(monkeypatch: pytest.MonkeyPatch) -> None:
    def forbidden(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("policy attempted I/O")

    monkeypatch.setattr("builtins.open", forbidden)
    monkeypatch.setattr("socket.socket", forbidden)
    monkeypatch.setattr("subprocess.run", forbidden)
    profile = _profile(malformed_structure=SafetyCheckState.UNKNOWN)
    request = _request()

    first = PDFAdmissionPolicy().evaluate(
        profile=profile,
        request=request,
        duplicate_of_acquisition_id=None,
    )
    second = PDFAdmissionPolicy().evaluate(
        profile=profile,
        request=request,
        duplicate_of_acquisition_id=None,
    )

    assert first == second
