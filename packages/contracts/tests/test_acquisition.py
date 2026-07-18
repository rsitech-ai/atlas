from datetime import UTC, datetime, timedelta, timezone
from typing import Any
from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError
from rsi_atlas_contracts import (
    AcquisitionMethod,
    AcquisitionRequest,
    AdmissionOutcome,
    ArtifactCommandContext,
    ArtifactDescriptor,
    ArtifactID,
    DocumentAdmissionRecord,
    DocumentLifecycle,
    NetworkProfile,
    PDFSafetyProfile,
    SafetyCheckState,
)


def _context() -> ArtifactCommandContext:
    return ArtifactCommandContext(
        tenant_id=uuid4(),
        workspace_id=uuid4(),
        actor_id=uuid4(),
        trace_id=uuid4(),
    )


def _request(**changes: Any) -> AcquisitionRequest:
    acquisition_id = changes.pop("acquisition_id", uuid4())
    values: dict[str, Any] = {
        "acquisition_id": acquisition_id,
        "method": AcquisitionMethod.MANUAL_CLI,
        "original_filename": "protocol-paper.pdf",
        "source_locator": f"manual-import:{acquisition_id}",
        "declared_media_type": "application/pdf",
        "collector_version": "atlas-cli-0.1.0",
        "network_profile": NetworkProfile.OFFLINE,
    }
    values.update(changes)
    return AcquisitionRequest(**values)


def _artifact() -> ArtifactDescriptor:
    digest = "a" * 64
    return ArtifactDescriptor(
        artifact_id=ArtifactID(f"sha256:{digest}"),
        digest=digest,
        size_bytes=512,
        media_type="application/pdf",
    )


def _profile(**changes: Any) -> PDFSafetyProfile:
    artifact = _artifact()
    values: dict[str, Any] = {
        "artifact_id": artifact.artifact_id,
        "digest": artifact.digest,
        "size_bytes": artifact.size_bytes,
        "header_version": "1.7",
        "eof_marker_present": True,
        "page_marker_count": 1,
        "mime_signature_consistency": SafetyCheckState.PASS,
        "size_limit": SafetyCheckState.PASS,
        "page_count_limit": SafetyCheckState.UNKNOWN,
        "encryption_password_state": SafetyCheckState.UNKNOWN,
        "malformed_structure": SafetyCheckState.UNKNOWN,
        "embedded_files": SafetyCheckState.UNKNOWN,
        "active_actions": SafetyCheckState.UNKNOWN,
        "suspicious_references": SafetyCheckState.UNKNOWN,
        "decompression_ratio": SafetyCheckState.UNKNOWN,
        "source_policy": SafetyCheckState.PASS,
        "available_disk": SafetyCheckState.PASS,
        "inspected_at": datetime(2026, 7, 18, 20, 30, tzinfo=UTC),
    }
    values.update(changes)
    return PDFSafetyProfile(**values)


def _record(**changes: Any) -> DocumentAdmissionRecord:
    values: dict[str, Any] = {
        "context": _context(),
        "request": _request(),
        "artifact": _artifact(),
        "profile": _profile(),
        "lifecycle": DocumentLifecycle.AWAITING_REVIEW,
        "outcome": AdmissionOutcome.QUARANTINE_FOR_REVIEW,
        "reason_codes": ("required_check_unknown",),
        "recorded_at": datetime(2026, 7, 18, 20, 31, tzinfo=UTC),
    }
    values.update(changes)
    return DocumentAdmissionRecord(**values)


def test_acquisition_request_is_strict_and_uses_an_opaque_locator() -> None:
    request = _request()

    assert request.schema_version == "1.0.0"
    assert request.source_locator == f"manual-import:{request.acquisition_id}"

    with pytest.raises(ValidationError, match="extra_forbidden"):
        AcquisitionRequest.model_validate({**request.model_dump(), "unexpected": True})


@pytest.mark.parametrize(
    "filename",
    (
        "",
        ".",
        "..",
        "/tmp/paper.pdf",
        "../paper.pdf",
        r"folder\paper.pdf",
        "paper.txt",
        "paper\u0000.pdf",
        "e\u0301vidence.pdf",
    ),
)
def test_acquisition_request_rejects_unsafe_or_noncanonical_filenames(filename: str) -> None:
    with pytest.raises(ValidationError):
        _request(original_filename=filename)


@pytest.mark.parametrize(
    "locator",
    (
        "file:///tmp/paper.pdf",
        "https://example.com/paper.pdf",
        "manual-import:not-a-uuid",
        f"manual-import:{uuid4()}\n",
    ),
)
def test_acquisition_request_rejects_paths_urls_and_invalid_locators(locator: str) -> None:
    with pytest.raises(ValidationError):
        _request(source_locator=locator)


def test_acquisition_locator_must_match_the_acquisition_identity() -> None:
    with pytest.raises(ValidationError, match="locator"):
        _request(source_locator=f"manual-import:{uuid4()}")


def test_safety_profile_requires_matching_artifact_identity() -> None:
    with pytest.raises(ValidationError, match="artifact"):
        _profile(artifact_id=ArtifactID(f"sha256:{'b' * 64}"))


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
def test_safety_profile_has_an_explicit_state_for_every_mandatory_check(field: str) -> None:
    payload = _profile().model_dump()
    payload.pop(field)

    with pytest.raises(ValidationError, match=field):
        PDFSafetyProfile.model_validate(payload)


def test_safety_profile_rejects_naive_or_non_utc_timestamps() -> None:
    with pytest.raises(ValidationError, match="UTC"):
        _profile(inspected_at=datetime(2026, 7, 18, 20, 30))
    with pytest.raises(ValidationError, match="UTC"):
        _profile(inspected_at=datetime(2026, 7, 18, 20, 30, tzinfo=timezone(timedelta(hours=2))))


@pytest.mark.parametrize(
    ("outcome", "lifecycle"),
    (
        (AdmissionOutcome.ACCEPT, DocumentLifecycle.AWAITING_REVIEW),
        (AdmissionOutcome.ACCEPT_WITH_RESTRICTIONS, DocumentLifecycle.AWAITING_REVIEW),
        (AdmissionOutcome.REGISTER_NEW_VERSION, DocumentLifecycle.AWAITING_REVIEW),
    ),
)
def test_phase_two_a_record_cannot_claim_acceptance(
    outcome: AdmissionOutcome, lifecycle: DocumentLifecycle
) -> None:
    with pytest.raises(ValidationError, match="Phase 2A"):
        _record(outcome=outcome, lifecycle=lifecycle)


@pytest.mark.parametrize(
    ("outcome", "lifecycle"),
    (
        (AdmissionOutcome.QUARANTINE_FOR_REVIEW, DocumentLifecycle.AWAITING_REVIEW),
        (AdmissionOutcome.REQUEST_PASSWORD, DocumentLifecycle.AWAITING_PASSWORD),
        (AdmissionOutcome.REJECT_POLICY_VIOLATION, DocumentLifecycle.REJECTED),
        (AdmissionOutcome.REJECT_UNSAFE, DocumentLifecycle.REJECTED),
        (AdmissionOutcome.MARK_EXACT_DUPLICATE, DocumentLifecycle.DUPLICATE),
    ),
)
def test_phase_two_a_outcome_lifecycle_matrix(
    outcome: AdmissionOutcome, lifecycle: DocumentLifecycle
) -> None:
    duplicate_id = uuid4() if outcome is AdmissionOutcome.MARK_EXACT_DUPLICATE else None
    record = _record(
        outcome=outcome,
        lifecycle=lifecycle,
        duplicate_of_acquisition_id=duplicate_id,
    )

    assert record.outcome is outcome
    assert record.lifecycle is lifecycle


def test_outcome_and_lifecycle_must_be_consistent() -> None:
    with pytest.raises(ValidationError, match="lifecycle"):
        _record(
            outcome=AdmissionOutcome.REJECT_UNSAFE,
            lifecycle=DocumentLifecycle.AWAITING_REVIEW,
        )


def test_duplicate_target_is_required_only_for_an_exact_duplicate() -> None:
    with pytest.raises(ValidationError, match="duplicate"):
        _record(
            outcome=AdmissionOutcome.MARK_EXACT_DUPLICATE,
            lifecycle=DocumentLifecycle.DUPLICATE,
        )
    with pytest.raises(ValidationError, match="duplicate"):
        _record(duplicate_of_acquisition_id=uuid4())


def test_record_requires_profile_and_artifact_to_match() -> None:
    with pytest.raises(ValidationError, match="profile"):
        _record(profile=_profile(size_bytes=513))


def test_reason_codes_are_nonempty_unique_and_canonical() -> None:
    with pytest.raises(ValidationError, match="reason"):
        _record(reason_codes=())
    with pytest.raises(ValidationError, match="reason"):
        _record(reason_codes=("z_reason", "a_reason"))
    with pytest.raises(ValidationError, match="reason"):
        _record(reason_codes=("same_reason", "same_reason"))


def test_record_rejects_naive_or_non_utc_timestamps() -> None:
    with pytest.raises(ValidationError, match="UTC"):
        _record(recorded_at=datetime(2026, 7, 18, 20, 31))
    with pytest.raises(ValidationError, match="UTC"):
        _record(
            recorded_at=datetime(
                2026,
                7,
                18,
                20,
                31,
                tzinfo=timezone(timedelta(hours=-4)),
            )
        )


def test_contract_json_round_trip_preserves_uuid_and_tuple_evidence() -> None:
    duplicate_id = UUID("77777777-7777-4777-8777-777777777777")
    record = _record(
        lifecycle=DocumentLifecycle.DUPLICATE,
        outcome=AdmissionOutcome.MARK_EXACT_DUPLICATE,
        duplicate_of_acquisition_id=duplicate_id,
    )

    decoded = DocumentAdmissionRecord.model_validate_json(record.model_dump_json())

    assert decoded == record
    assert decoded.duplicate_of_acquisition_id == duplicate_id
