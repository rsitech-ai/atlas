from datetime import UTC, datetime, timedelta, timezone
from decimal import Decimal
from hashlib import sha256
from json import dumps
from math import inf, nan
from pathlib import Path
from typing import Any
from uuid import UUID

import pytest
from pydantic import ValidationError
from rsi_atlas_contracts import (
    AcquisitionMethod,
    AcquisitionRequest,
    AdmissionAssessment,
    AdmissionAssessmentDraft,
    AdmissionOutcome,
    ArtifactCommandContext,
    ArtifactDescriptor,
    ArtifactID,
    BoundingBox,
    CanonicalDocument,
    CanonicalDocumentManifest,
    CanonicalDocumentManifestDraft,
    CanonicalPage,
    CanonicalTextElement,
    CanonicalTextRole,
    CoordinateSystem,
    DocumentAdmissionRecord,
    DocumentLifecycle,
    DocumentPreflightProfile,
    DocumentProcessingLifecycle,
    DocumentProfilerIdentity,
    GovernanceApprovalRecord,
    GovernanceRecordReference,
    GovernanceSubjectKind,
    NetworkProfile,
    PageGeometry,
    ParserCandidateIdentity,
    ParserCandidatePage,
    ParserQualityDecision,
    ParserQualityReport,
    ParserRunReference,
    ParserRunRequest,
    ParserRunResult,
    ParserRunStatus,
    ParserSpan,
    PDFSafetyProfile,
    SafetyCheckState,
    build_canonical_document,
    build_governance_approval_record,
    canonical_element_identifier,
    canonicalization_identifier,
    document_admission_record_hash,
    parser_span_source_hash,
    sha256_text,
)

TENANT_ID = UUID("00000000-0000-4000-8000-000000000001")
WORKSPACE_ID = UUID("00000000-0000-4000-8000-000000000002")
ACTOR_ID = UUID("00000000-0000-4000-8000-000000000003")
TRACE_ID = UUID("00000000-0000-4000-8000-000000000004")
ACQUISITION_ID = UUID("00000000-0000-4000-8000-000000000005")
PREFLIGHT_RUN_ID = UUID("00000000-0000-4000-8000-000000000006")
PARSER_RUN_ID = UUID("00000000-0000-4000-8000-000000000007")
ASSESSMENT_ID = UUID("00000000-0000-4000-8000-000000000008")
MANIFEST_ID = UUID("00000000-0000-4000-8000-000000000009")
DIGEST = "a" * 64
CONFIG_HASH = "b" * 64
BUILD_HASH = "c" * 64
OUTPUT_DIGEST = "d" * 64
GOVERNANCE_HASH = "e" * 64
BENCHMARK_HASH = "f" * 64
NORMALIZER_HASH = "1" * 64
NOW = datetime(2026, 7, 19, 8, 0, tzinfo=UTC)
FIXTURES = Path(__file__).parent / "fixtures"


def _d(value: str) -> Decimal:
    return Decimal(value)


def _context(**changes: Any) -> ArtifactCommandContext:
    values: dict[str, Any] = {
        "tenant_id": TENANT_ID,
        "workspace_id": WORKSPACE_ID,
        "actor_id": ACTOR_ID,
        "trace_id": TRACE_ID,
    }
    values.update(changes)
    return ArtifactCommandContext(**values)


def _artifact(
    digest: str = DIGEST,
    *,
    media_type: str = "application/pdf",
    size_bytes: int = 4096,
) -> ArtifactDescriptor:
    return ArtifactDescriptor(
        artifact_id=ArtifactID(f"sha256:{digest}"),
        digest=digest,
        size_bytes=size_bytes,
        media_type=media_type,
    )


def _request(**changes: Any) -> AcquisitionRequest:
    acquisition_id = changes.pop("acquisition_id", ACQUISITION_ID)
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


def _phase_two_a_profile(**changes: Any) -> PDFSafetyProfile:
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
        "inspected_at": NOW - timedelta(seconds=2),
    }
    values.update(changes)
    return PDFSafetyProfile(**values)


def _prior_admission(**changes: Any) -> DocumentAdmissionRecord:
    values: dict[str, Any] = {
        "context": _context(),
        "request": _request(),
        "artifact": _artifact(),
        "profile": _phase_two_a_profile(),
        "lifecycle": DocumentLifecycle.AWAITING_REVIEW,
        "outcome": AdmissionOutcome.QUARANTINE_FOR_REVIEW,
        "reason_codes": ("required_check_unknown",),
        "recorded_at": NOW - timedelta(seconds=1),
    }
    values.update(changes)
    return DocumentAdmissionRecord(**values)


def _profiler(**changes: Any) -> DocumentProfilerIdentity:
    values: dict[str, Any] = {
        "profiler_id": "pypdf_preflight",
        "name": "pypdf-preflight",
        "version": "6.14.2",
        "build_hash": BUILD_HASH,
        "configuration_hash": CONFIG_HASH,
    }
    values.update(changes)
    return DocumentProfilerIdentity(**values)


def _candidate(**changes: Any) -> ParserCandidateIdentity:
    values: dict[str, Any] = {
        "parser_id": "pdfminer_tier0",
        "name": "pdfminer.six",
        "version": "20260107",
        "tier": 0,
        "build_hash": BUILD_HASH,
        "configuration_hash": CONFIG_HASH,
    }
    values.update(changes)
    return ParserCandidateIdentity(**values)


def _governance_record(
    *,
    kind: GovernanceSubjectKind = GovernanceSubjectKind.PROFILER,
    **changes: Any,
) -> GovernanceApprovalRecord:
    subject = _profiler() if kind is GovernanceSubjectKind.PROFILER else _candidate()
    subject_id = (
        subject.profiler_id if isinstance(subject, DocumentProfilerIdentity) else subject.parser_id
    )
    values: dict[str, Any] = {
        "subject_kind": kind,
        "subject_id": subject_id,
        "subject_build_hash": subject.build_hash,
        "subject_configuration_hash": subject.configuration_hash,
        "policy_version": "pdf-development-1",
        "benchmark_hash": BENCHMARK_HASH,
        "approved_by": ACTOR_ID,
        "approved_at": NOW - timedelta(seconds=3),
    }
    values.update(changes)
    return build_governance_approval_record(**values)


def _governance(
    *, kind: GovernanceSubjectKind = GovernanceSubjectKind.PROFILER, **changes: Any
) -> GovernanceRecordReference:
    return _governance_record(kind=kind, **changes).reference()


def _raw_box(**changes: Any) -> BoundingBox:
    values: dict[str, Any] = {
        "coordinate_system": CoordinateSystem.PDF_BOTTOM_LEFT_POINTS,
        "left": _d("72.000000"),
        "top": _d("720.000000"),
        "right": _d("360.000000"),
        "bottom": _d("700.000000"),
    }
    values.update(changes)
    return BoundingBox(**values)


def _normalized_box(**changes: Any) -> BoundingBox:
    values: dict[str, Any] = {
        "coordinate_system": CoordinateSystem.NORMALIZED_TOP_LEFT,
        "left": _d("0.100000"),
        "top": _d("0.100000"),
        "right": _d("0.900000"),
        "bottom": _d("0.200000"),
    }
    values.update(changes)
    return BoundingBox(**values)


def _geometry(page_number: int = 1, **changes: Any) -> PageGeometry:
    values: dict[str, Any] = {
        "page_number": page_number,
        "media_box": BoundingBox(
            coordinate_system=CoordinateSystem.PDF_BOTTOM_LEFT_POINTS,
            left=_d("0.000000"),
            top=_d("792.000000"),
            right=_d("612.000000"),
            bottom=_d("0.000000"),
        ),
        "crop_box": BoundingBox(
            coordinate_system=CoordinateSystem.PDF_BOTTOM_LEFT_POINTS,
            left=_d("0.000000"),
            top=_d("792.000000"),
            right=_d("612.000000"),
            bottom=_d("0.000000"),
        ),
        "rotation_degrees": 0,
    }
    values.update(changes)
    return PageGeometry(**values)


def _preflight(**changes: Any) -> DocumentPreflightProfile:
    values: dict[str, Any] = {
        "preflight_run_id": PREFLIGHT_RUN_ID,
        "context": _context(),
        "acquisition_id": ACQUISITION_ID,
        "artifact": _artifact(),
        "profiler": _profiler(),
        "page_count": 1,
        "pages": (_geometry(),),
        "encryption_password_state": SafetyCheckState.PASS,
        "malformed_structure": SafetyCheckState.PASS,
        "embedded_files": SafetyCheckState.PASS,
        "active_actions": SafetyCheckState.PASS,
        "suspicious_references": SafetyCheckState.PASS,
        "decompression_ratio": SafetyCheckState.PASS,
        "decoded_stream_bytes": 1024,
        "character_count": 128,
        "image_only_page_count": 0,
        "warnings": (),
        "profiled_at": NOW,
    }
    values.update(changes)
    return DocumentPreflightProfile(**values)


def _assessment(**changes: Any) -> AdmissionAssessment:
    prior_admission = changes.pop("prior_admission", _prior_admission())
    prior_admission_hash = changes.pop(
        "prior_admission_hash", document_admission_record_hash(prior_admission)
    )
    promotion_record = changes.pop("promotion_record", _governance_record())
    values: dict[str, Any] = {
        "assessment_id": ASSESSMENT_ID,
        "context": _context(),
        "acquisition_id": ACQUISITION_ID,
        "artifact": _artifact(),
        "prior_admission_hash": prior_admission_hash,
        "preflight": _preflight(),
        "promotion": _governance(),
        "lifecycle": DocumentProcessingLifecycle.PREFLIGHTED,
        "outcome": AdmissionOutcome.ACCEPT,
        "reason_codes": ("authoritative_preflight_passed",),
        "assessed_at": NOW,
    }
    values.update(changes)
    draft = AdmissionAssessmentDraft(**values)
    return AdmissionAssessment.from_resolved_records(
        draft,
        prior_admission=prior_admission,
        promotion=promotion_record,
    )


def _run_request(*, parser_run_id: UUID = PARSER_RUN_ID, **changes: Any) -> ParserRunRequest:
    values: dict[str, Any] = {
        "parser_run_id": parser_run_id,
        "context": _context(),
        "acquisition_id": ACQUISITION_ID,
        "artifact": _artifact(),
        "candidate": _candidate(),
        "page_numbers": (1,),
        "maximum_output_bytes": 1_048_576,
    }
    values.update(changes)
    return ParserRunRequest(**values)


def _span(**changes: Any) -> ParserSpan:
    raw_text = changes.pop("raw_text", "Bitcoin settles every ten minutes.")
    normalized_text = changes.pop("normalized_text", raw_text)
    values: dict[str, Any] = {
        "span_id": "span_0001",
        "page_number": 1,
        "reading_order": 0,
        "bounding_box": _raw_box(),
        "raw_text": raw_text,
        "raw_text_hash": sha256_text(raw_text),
        "normalized_text": normalized_text,
        "normalized_text_hash": sha256_text(normalized_text),
        "font_name": "Inter",
        "font_size_points": _d("11.000000"),
        "warnings": (),
    }
    values.update(changes)
    return ParserSpan(**values)


def _candidate_page(**changes: Any) -> ParserCandidatePage:
    values: dict[str, Any] = {
        "page_number": 1,
        "geometry": _geometry(),
        "spans": (_span(),),
        "image_count": 0,
        "warnings": (),
    }
    values.update(changes)
    return ParserCandidatePage(**values)


def _run_result(
    *, parser_run_id: UUID = PARSER_RUN_ID, finished_at: datetime | None = None, **changes: Any
) -> ParserRunResult:
    values: dict[str, Any] = {
        "request": _run_request(parser_run_id=parser_run_id),
        "status": ParserRunStatus.SUCCEEDED,
        "pages": (_candidate_page(),),
        "output_artifact": _artifact(
            OUTPUT_DIGEST,
            media_type="application/vnd.rsi-atlas.parser-result+json",
            size_bytes=2048,
        ),
        "warnings": (),
        "started_at": NOW,
        "finished_at": finished_at or NOW + timedelta(seconds=1),
    }
    values.update(changes)
    return ParserRunResult(**values)


def _quality(*, parser_run_id: UUID = PARSER_RUN_ID, **changes: Any) -> ParserQualityReport:
    values: dict[str, Any] = {
        "parser_run_id": parser_run_id,
        "candidate": _candidate(),
        "page_count": 1,
        "pages_with_content": 1,
        "page_coverage": 1.0,
        "replacement_character_rate": 0.0,
        "crypto_token_preservation_rate": 1.0,
        "valid_bounding_box_rate": 1.0,
        "deterministic_output_hash": OUTPUT_DIGEST,
        "decision": ParserQualityDecision.QUALIFIED,
        "warnings": (),
        "evaluated_at": NOW + timedelta(seconds=2),
    }
    values.update(changes)
    return ParserQualityReport(**values)


def _canonicalization_id() -> str:
    candidate = _candidate()
    return canonicalization_identifier(
        artifact_digest=DIGEST,
        parser_build_hash=candidate.build_hash,
        parser_configuration_hash=candidate.configuration_hash,
        normalizer_version="nfc-1",
        normalizer_configuration_hash=NORMALIZER_HASH,
    )


def _canonical_element(**changes: Any) -> CanonicalTextElement:
    raw_text = changes.pop("raw_text", "Bitcoin settles every ten minutes.")
    normalized_text = changes.pop("normalized_text", raw_text)
    box = changes.pop("bounding_box", _normalized_box())
    raw_hash = sha256_text(raw_text)
    canonicalization_id = changes.pop("canonicalization_id", _canonicalization_id())
    values: dict[str, Any] = {
        "kind": "text",
        "role": CanonicalTextRole.PARAGRAPH,
        "canonicalization_id": canonicalization_id,
        "element_id": canonical_element_identifier(
            canonicalization_id=canonicalization_id,
            page_number=1,
            kind="text",
            reading_order=0,
            bounding_box=box,
            raw_text_hash=raw_hash,
        ),
        "page_number": 1,
        "reading_order": 0,
        "bounding_box": box,
        "raw_bounding_box": _raw_box(),
        "raw_text": raw_text,
        "raw_text_hash": raw_hash,
        "normalized_text": normalized_text,
        "normalized_text_hash": sha256_text(normalized_text),
        "parent_section_id": None,
        "parser_confidence": 1.0,
        "ocr_confidence": None,
        "language": "unknown",
        "source_output_artifact_digest": OUTPUT_DIGEST,
        "source_span_id": "span_0001",
        "source_span_hash": parser_span_source_hash(
            source_output_artifact_digest=OUTPUT_DIGEST,
            candidate=_candidate(),
            span_id="span_0001",
            page_number=1,
            reading_order=0,
            raw_bounding_box=_raw_box(),
            raw_text_hash=raw_hash,
        ),
        "source_hash": parser_span_source_hash(
            source_output_artifact_digest=OUTPUT_DIGEST,
            candidate=_candidate(),
            span_id="span_0001",
            page_number=1,
            reading_order=0,
            raw_bounding_box=_raw_box(),
            raw_text_hash=raw_hash,
        ),
    }
    values.update(changes)
    return CanonicalTextElement(**values)


def _canonical_page(**changes: Any) -> CanonicalPage:
    values: dict[str, Any] = {
        "canonicalization_id": _canonicalization_id(),
        "source_artifact_digest": DIGEST,
        "page_number": 1,
        "geometry": _geometry(),
        "elements": (_canonical_element(),),
    }
    values.update(changes)
    return CanonicalPage(**values)


def _canonical_document(**changes: Any) -> CanonicalDocument:
    values: dict[str, Any] = {
        "source_artifact_digest": DIGEST,
        "candidate": _candidate(),
        "normalizer_version": "nfc-1",
        "normalizer_configuration_hash": NORMALIZER_HASH,
        "pages": (_canonical_page(),),
    }
    values.update(changes)
    return build_canonical_document(**values)


def _manifest(
    *,
    parser_run_id: UUID = PARSER_RUN_ID,
    finished_at: datetime | None = None,
    **changes: Any,
) -> CanonicalDocumentManifest:
    result = _run_result(parser_run_id=parser_run_id, finished_at=finished_at)
    document = _canonical_document()
    content_hash = sha256(document.canonical_json_bytes()).hexdigest()
    qualification_record = changes.pop(
        "qualification_record", _governance_record(kind=GovernanceSubjectKind.PARSER)
    )
    values: dict[str, Any] = {
        "manifest_id": MANIFEST_ID,
        "context": _context(),
        "acquisition_id": ACQUISITION_ID,
        "artifact": _artifact(),
        "source_run": ParserRunReference.from_result(result),
        "quality": _quality(parser_run_id=parser_run_id),
        "qualification": qualification_record.reference(),
        "canonical_document": document,
        "document_version_id": f"canonical:{content_hash}",
        "canonical_content_hash": content_hash,
        "canonical_artifact": _artifact(
            content_hash,
            media_type="application/vnd.rsi-atlas.canonical+json",
            size_bytes=len(document.canonical_json_bytes()),
        ),
        "lifecycle": DocumentProcessingLifecycle.CANONICALIZED,
        "recorded_at": (finished_at or NOW + timedelta(seconds=1)) + timedelta(seconds=2),
    }
    values.update(changes)
    draft = CanonicalDocumentManifestDraft(**values)
    return CanonicalDocumentManifest.from_resolved_record(
        draft,
        qualification_record=qualification_record,
    )


def test_nested_models_forbid_unknown_fields_and_schema_drift() -> None:
    payload = _preflight().model_dump(mode="json")
    payload["pages"][0]["crop_box"]["unexpected"] = True
    with pytest.raises(ValidationError, match="extra_forbidden"):
        DocumentPreflightProfile.model_validate_json(dumps(payload))

    payload = _manifest().model_dump(mode="json")
    payload["schema_version"] = "1.0.1"
    with pytest.raises(ValidationError, match="schema_version"):
        CanonicalDocumentManifest.model_validate_json(dumps(payload))


@pytest.mark.parametrize("value", (nan, inf, -inf, "0.5", 0.5, True))
def test_bounding_boxes_reject_non_decimal_or_non_finite_coordinates(value: object) -> None:
    with pytest.raises((ValidationError, TypeError)):
        _normalized_box(left=value)


def test_coordinates_support_negative_offset_crop_boxes_and_rotation() -> None:
    media = BoundingBox(
        coordinate_system=CoordinateSystem.PDF_BOTTOM_LEFT_POINTS,
        left=_d("-100.000000"),
        bottom=_d("-50.000000"),
        right=_d("500.000000"),
        top=_d("750.000000"),
    )
    crop = BoundingBox(
        coordinate_system=CoordinateSystem.PDF_BOTTOM_LEFT_POINTS,
        left=_d("-50.000000"),
        bottom=_d("-25.000000"),
        right=_d("450.000000"),
        top=_d("725.000000"),
    )
    geometry = _geometry(media_box=media, crop_box=crop, rotation_degrees=270)

    assert geometry.width_points == _d("500.000000")
    assert geometry.height_points == _d("750.000000")
    assert geometry.rotation_degrees == 270


def test_fixed_point_coordinates_normalize_negative_zero_and_encoding() -> None:
    first = _normalized_box(left=_d("-0.000000"))
    second = _normalized_box(left=_d("0.000000"))
    third = _normalized_box(left=_d("0"))

    assert first == second == third
    assert first.canonical_payload()["left"] == "0.000000"
    kwargs = {
        "canonicalization_id": _canonicalization_id(),
        "page_number": 1,
        "kind": "text",
        "reading_order": 0,
        "raw_text_hash": sha256_text("same"),
    }
    first_id = canonical_element_identifier(bounding_box=first, **kwargs)
    third_id = canonical_element_identifier(bounding_box=third, **kwargs)
    assert first_id == third_id

    numeric_json = BoundingBox.model_validate_json(
        '{"coordinate_system":"normalized_top_left","left":-0.0,"top":0.1,"right":0.9,"bottom":0.2}'
    )
    fixed_string_json = BoundingBox.model_validate_json(
        '{"coordinate_system":"normalized_top_left","left":"0.000000",'
        '"top":"0.100000","right":"0.900000","bottom":"0.200000"}'
    )
    assert numeric_json.canonical_json_bytes() == fixed_string_json.canonical_json_bytes()


def test_crop_box_must_be_inside_media_box() -> None:
    outside = _raw_box(left=_d("-1.000000"))
    with pytest.raises(ValidationError, match="crop_box"):
        _geometry(crop_box=outside)


def test_acceptance_requires_exact_prior_admission_and_resolved_promotion() -> None:
    with pytest.raises(ValidationError, match="promotion"):
        _assessment(promotion=None)
    forged = _governance(subject_id="other_profiler")
    with pytest.raises(ValidationError, match="promotion"):
        _assessment(promotion=forged)
    record_payload = _governance_record().model_dump()
    record_payload["benchmark_hash"] = "2" * 64
    with pytest.raises(ValidationError, match="immutable record content"):
        GovernanceApprovalRecord.model_validate(record_payload)
    with pytest.raises(ValidationError, match="prior admission hash"):
        _assessment(prior_admission_hash="2" * 64)


def test_public_decoder_cannot_self_attest_assessment_authority() -> None:
    assessment_payload = _assessment().model_dump(mode="json")
    draft = AdmissionAssessmentDraft.model_validate_json(dumps(assessment_payload))
    assert draft.outcome is AdmissionOutcome.ACCEPT

    with pytest.raises(ValidationError, match="authority"):
        AdmissionAssessment.model_validate_json(dumps(assessment_payload))


@pytest.mark.parametrize(
    ("lifecycle", "outcome"),
    (
        (DocumentLifecycle.REJECTED, AdmissionOutcome.REJECT_UNSAFE),
        (DocumentLifecycle.DUPLICATE, AdmissionOutcome.MARK_EXACT_DUPLICATE),
    ),
)
def test_rejected_or_duplicate_prior_admission_cannot_be_reassessed(
    lifecycle: DocumentLifecycle, outcome: AdmissionOutcome
) -> None:
    prior = _prior_admission(
        lifecycle=lifecycle,
        outcome=outcome,
        duplicate_of_acquisition_id=(
            UUID(int=99) if lifecycle is DocumentLifecycle.DUPLICATE else None
        ),
    )
    with pytest.raises(ValidationError, match="not eligible"):
        _assessment(prior_admission=prior)


def test_assessment_binds_prior_tenant_workspace_acquisition_artifact_and_hard_checks() -> None:
    with pytest.raises(ValidationError, match="workspace"):
        _assessment(context=_context(workspace_id=UUID(int=99)))
    with pytest.raises(ValidationError, match="acquisition"):
        _assessment(acquisition_id=UUID(int=98))
    with pytest.raises(ValidationError, match="artifact"):
        _assessment(artifact=_artifact("2" * 64))
    unsafe_prior = _prior_admission(
        profile=_phase_two_a_profile(source_policy=SafetyCheckState.FAIL)
    )
    with pytest.raises(ValidationError, match="hard checks"):
        _assessment(prior_admission=unsafe_prior)


def test_preflight_unknown_page_evidence_routes_without_fabrication() -> None:
    profile = _preflight(
        page_count=None,
        pages=(),
        image_only_page_count=None,
        encryption_password_state=SafetyCheckState.FAIL,
        warnings=("password_required",),
    )
    assessment = _assessment(
        preflight=profile,
        promotion=None,
        lifecycle=DocumentProcessingLifecycle.AWAITING_PASSWORD,
        outcome=AdmissionOutcome.REQUEST_PASSWORD,
        reason_codes=("password_required",),
    )
    assert assessment.lifecycle is DocumentProcessingLifecycle.AWAITING_PASSWORD


def test_acceptance_requires_authoritative_preflight_checks() -> None:
    with pytest.raises(ValidationError, match="authoritative"):
        _assessment(preflight=_preflight(active_actions=SafetyCheckState.UNKNOWN))


def test_reason_and_warning_codes_are_sorted_unique_identifiers() -> None:
    with pytest.raises(ValidationError, match="warnings"):
        _preflight(warnings=("z_warning", "a_warning"))
    with pytest.raises(ValidationError, match="reason"):
        _assessment(reason_codes=("z_reason", "a_reason"))


def test_parser_result_binds_request_pages_output_and_terminal_time() -> None:
    with pytest.raises(ValidationError, match="page"):
        _run_result(pages=(_candidate_page(page_number=2),))
    with pytest.raises(ValidationError, match="output"):
        _run_result(output_artifact=None)
    with pytest.raises(ValidationError, match="finished_at"):
        _run_result(finished_at=NOW - timedelta(seconds=1))


def test_parser_output_size_enforces_exact_request_boundary() -> None:
    request = _run_request(maximum_output_bytes=2048)
    assert _run_result(request=request).output_artifact is not None
    with pytest.raises(ValidationError, match="output size"):
        _run_result(
            request=request,
            output_artifact=_artifact(
                OUTPUT_DIGEST,
                media_type="application/vnd.rsi-atlas.parser-result+json",
                size_bytes=2049,
            ),
        )


def test_parser_spans_validate_text_hashes_nfc_controls_and_order() -> None:
    with pytest.raises(ValidationError, match="raw_text_hash"):
        _span(raw_text_hash="2" * 64)
    with pytest.raises(ValidationError, match="normalized_text"):
        _span(normalized_text="e\u0301")
    with pytest.raises(ValidationError, match="control"):
        _span(raw_text="unsafe\u0000text")
    with pytest.raises(ValidationError, match="reading order"):
        _candidate_page(spans=(_span(), _span(span_id="span_0002")))


def test_parser_run_reference_is_content_addressed() -> None:
    reference = ParserRunReference.from_result(_run_result())
    payload = reference.model_dump()
    payload["result_hash"] = "2" * 64
    with pytest.raises(ValidationError, match="reference_id"):
        ParserRunReference.model_validate(payload)


def test_canonical_content_is_identical_across_distinct_audit_runs() -> None:
    first = _manifest(parser_run_id=PARSER_RUN_ID, finished_at=NOW + timedelta(seconds=1))
    second = _manifest(parser_run_id=UUID(int=99), finished_at=NOW + timedelta(seconds=20))

    assert first.source_run.parser_run_id != second.source_run.parser_run_id
    assert first.recorded_at != second.recorded_at
    assert first.document_version_id == second.document_version_id
    assert first.canonical_content_hash == second.canonical_content_hash
    assert (
        first.canonical_document.canonical_json_bytes()
        == second.canonical_document.canonical_json_bytes()
    )


def test_canonical_element_ids_and_text_hashes_are_deterministic() -> None:
    element = _canonical_element()
    assert element.element_id == canonical_element_identifier(
        canonicalization_id=element.canonicalization_id,
        page_number=element.page_number,
        kind=element.kind,
        reading_order=element.reading_order,
        bounding_box=element.bounding_box,
        raw_text_hash=element.raw_text_hash,
    )
    with pytest.raises(ValidationError, match="element_id"):
        _canonical_element(element_id="element:" + "2" * 64)
    with pytest.raises(ValidationError, match="normalized_text_hash"):
        _canonical_element(normalized_text_hash="2" * 64)


def test_canonical_document_rejects_missing_duplicate_or_foreign_pages() -> None:
    with pytest.raises((ValidationError, ValueError), match="pages"):
        _canonical_document(pages=())
    page = _canonical_page()
    second_page = page.model_copy(update={"page_number": 1})
    with pytest.raises((ValidationError, ValueError), match="page"):
        _canonical_document(pages=(page, second_page))
    foreign = page.model_copy(update={"source_artifact_digest": "2" * 64})
    with pytest.raises((ValidationError, ValueError), match="source artifact"):
        _canonical_document(pages=(foreign,))


def test_manifest_requires_qualified_resolved_parser_lineage() -> None:
    with pytest.raises(ValidationError, match="qualified"):
        _manifest(quality=_quality(decision=ParserQualityDecision.REVIEW_REQUIRED))
    with pytest.raises(ValidationError, match="qualification"):
        _manifest(qualification=_governance())
    other_candidate = _candidate(configuration_hash="2" * 64)
    with pytest.raises(ValidationError, match="candidate"):
        _manifest(quality=_quality(candidate=other_candidate))
    with pytest.raises(ValidationError, match="output hash"):
        _manifest(quality=_quality(deterministic_output_hash="2" * 64))


def test_public_decoder_cannot_self_attest_manifest_qualification() -> None:
    payload = _manifest().model_dump(mode="json")
    assert CanonicalDocumentManifestDraft.model_validate_json(dumps(payload)).qualification
    with pytest.raises(ValidationError, match="authority"):
        CanonicalDocumentManifest.model_validate_json(dumps(payload))


def test_manifest_rejects_invented_self_hashed_canonical_element() -> None:
    invented = _canonical_element(raw_text="Invented parser text")
    page = _canonical_page(elements=(invented,))
    document = _canonical_document(pages=(page,))
    content_hash = sha256(document.canonical_json_bytes()).hexdigest()
    artifact = _artifact(
        content_hash,
        media_type="application/vnd.rsi-atlas.canonical+json",
        size_bytes=len(document.canonical_json_bytes()),
    )
    with pytest.raises(ValidationError, match="retained parser span"):
        _manifest(
            canonical_document=document,
            canonical_content_hash=content_hash,
            document_version_id=f"canonical:{content_hash}",
            canonical_artifact=artifact,
        )


def test_manifest_requires_exact_canonical_artifact_byte_size() -> None:
    manifest = _manifest()
    descriptor = manifest.canonical_artifact.model_copy(
        update={"size_bytes": manifest.canonical_artifact.size_bytes + 1}
    )
    with pytest.raises(ValidationError, match="artifact size"):
        _manifest(canonical_artifact=descriptor)


def test_manifest_rejects_cross_workspace_acquisition_and_artifact_lineage() -> None:
    foreign_workspace = ParserRunReference.from_result(
        _run_result(request=_run_request(context=_context(workspace_id=UUID(int=99))))
    )
    with pytest.raises(ValidationError, match="workspace"):
        _manifest(source_run=foreign_workspace)
    foreign_acquisition = ParserRunReference.from_result(
        _run_result(request=_run_request(acquisition_id=UUID(int=98)))
    )
    with pytest.raises(ValidationError, match="acquisition"):
        _manifest(source_run=foreign_acquisition)
    foreign_artifact = ParserRunReference.from_result(
        _run_result(request=_run_request(artifact=_artifact("2" * 64)))
    )
    with pytest.raises(ValidationError, match="artifact"):
        _manifest(source_run=foreign_artifact)


def test_manifest_rejects_quality_for_another_run_and_canonical_digest_mismatch() -> None:
    with pytest.raises(ValidationError, match="parser run"):
        _manifest(quality=_quality(parser_run_id=UUID(int=99)))
    with pytest.raises(ValidationError, match="digest"):
        _manifest(
            canonical_artifact=_artifact(
                "2" * 64, media_type="application/vnd.rsi-atlas.canonical+json"
            )
        )


@pytest.mark.parametrize("field", ("profiled_at", "assessed_at", "evaluated_at", "recorded_at"))
def test_contract_timestamps_require_timezone_aware_utc(field: str) -> None:
    factories: dict[str, Any] = {
        "profiled_at": _preflight,
        "assessed_at": _assessment,
        "evaluated_at": _quality,
        "recorded_at": _manifest,
    }
    factory = factories[field]
    with pytest.raises(ValidationError, match="UTC"):
        factory(**{field: NOW.replace(tzinfo=None)})
    with pytest.raises(ValidationError, match="UTC"):
        factory(**{field: NOW.astimezone(timezone(timedelta(hours=2)))})


def test_contracts_round_trip_frozen_json_fixtures() -> None:
    preflight = DocumentPreflightProfile.model_validate_json(
        (FIXTURES / "document_preflight_v1.json").read_text(encoding="utf-8")
    )
    canonical = CanonicalDocument.model_validate_json(
        (FIXTURES / "canonical_document_v1.json").read_text(encoding="utf-8")
    )
    assert preflight == _preflight()
    assert canonical == _canonical_document()
