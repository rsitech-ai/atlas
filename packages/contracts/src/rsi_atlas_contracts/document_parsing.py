from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation
from enum import StrEnum
from hashlib import sha256
from json import dumps
from typing import Annotated, Literal, Self
from unicodedata import category, normalize
from uuid import UUID

from pydantic import (
    ConfigDict,
    Field,
    StrictFloat,
    StrictInt,
    field_validator,
    model_validator,
)

from rsi_atlas_contracts.acquisition import (
    AdmissionOutcome,
    DocumentAdmissionRecord,
    DocumentLifecycle,
    SafetyCheckState,
)
from rsi_atlas_contracts.artifact import ArtifactCommandContext, ArtifactDescriptor, ArtifactID
from rsi_atlas_contracts.system_status import StrictModel

_IDENTIFIER_PATTERN = r"^[a-z][a-z0-9_]{0,63}$"
_VERSION_PATTERN = r"^[a-z0-9][a-z0-9._-]{0,63}$"
_SHA256_PATTERN = r"^[0-9a-f]{64}$"
_ELEMENT_ID_PATTERN = r"^element:[0-9a-f]{64}$"
_CANONICAL_ID_PATTERN = r"^canonical:[0-9a-f]{64}$"
_CANONICALIZATION_KEY_PATTERN = r"^canonicalization:[0-9a-f]{64}$"
_GOVERNANCE_RECORD_PATTERN = r"^governance:[0-9a-f]{64}$"
_RUN_REFERENCE_PATTERN = r"^parser-run:[0-9a-f]{64}$"
_ALLOWED_TEXT_CONTROLS = {"\n", "\r", "\t"}
_COORDINATE_QUANTUM = Decimal("0.000001")
_MAX_COORDINATE = Decimal("1000000.000000")


class DocumentContractModel(StrictModel):
    model_config = ConfigDict(
        arbitrary_types_allowed=True,
        extra="forbid",
        frozen=True,
        strict=True,
    )

    def canonical_json_bytes(self) -> bytes:
        return _canonical_json(self.model_dump(mode="json"))


class CoordinateSystem(StrEnum):
    PDF_BOTTOM_LEFT_POINTS = "pdf_bottom_left_points"
    NORMALIZED_TOP_LEFT = "normalized_top_left"


class GovernanceSubjectKind(StrEnum):
    PROFILER = "profiler"
    PARSER = "parser"


class DocumentProcessingLifecycle(StrEnum):
    PREFLIGHTED = "preflighted"
    PARSING = "parsing"
    PARSE_VALIDATED = "parse_validated"
    CANONICALIZED = "canonicalized"
    CHUNKED = "chunked"
    INDEX_VALIDATED = "index_validated"
    PUBLISHED = "published"
    AWAITING_REVIEW = "awaiting_review"
    AWAITING_PASSWORD = "awaiting_password"
    FAILED_RETRYABLE = "failed_retryable"
    FAILED_TERMINAL = "failed_terminal"


class ParserRunStatus(StrEnum):
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    TIMED_OUT = "timed_out"
    KILLED = "killed"
    CANCELLED = "cancelled"
    INVALID_OUTPUT = "invalid_output"


class ParserQualityDecision(StrEnum):
    QUALIFIED = "qualified"
    REVIEW_REQUIRED = "review_required"
    REJECTED = "rejected"


class CanonicalTextRole(StrEnum):
    HEADING = "heading"
    PARAGRAPH = "paragraph"
    LIST_ITEM = "list_item"
    CAPTION = "caption"
    FOOTNOTE = "footnote"
    REFERENCE = "reference"
    ANNOTATION = "annotation"


def sha256_text(value: str) -> str:
    return sha256(value.encode("utf-8")).hexdigest()


def document_admission_record_hash(record: DocumentAdmissionRecord) -> str:
    return sha256(_canonical_json(record.model_dump(mode="json"))).hexdigest()


def canonicalization_identifier(
    *,
    artifact_digest: str,
    parser_build_hash: str,
    parser_configuration_hash: str,
    normalizer_version: str,
    normalizer_configuration_hash: str,
) -> str:
    payload = {
        "artifact_digest": artifact_digest,
        "normalizer_configuration_hash": normalizer_configuration_hash,
        "normalizer_version": normalizer_version,
        "parser_build_hash": parser_build_hash,
        "parser_configuration_hash": parser_configuration_hash,
    }
    return f"canonicalization:{sha256(_canonical_json(payload)).hexdigest()}"


def canonical_document_identifier(*, content_hash: str) -> str:
    return f"canonical:{content_hash}"


def canonical_element_identifier(
    *,
    canonicalization_id: str,
    page_number: int,
    kind: str,
    reading_order: int,
    bounding_box: BoundingBox,
    raw_text_hash: str,
) -> str:
    payload = {
        "bounding_box": bounding_box.canonical_payload(),
        "canonicalization_id": canonicalization_id,
        "kind": kind,
        "page_number": page_number,
        "raw_text_hash": raw_text_hash,
        "reading_order": reading_order,
    }
    return f"element:{sha256(_canonical_json(payload)).hexdigest()}"


def parser_span_source_hash(
    *,
    source_output_artifact_digest: str,
    candidate: ParserCandidateIdentity,
    span_id: str,
    page_number: int,
    reading_order: int,
    raw_bounding_box: BoundingBox,
    raw_text_hash: str,
) -> str:
    payload = {
        "candidate": candidate.model_dump(mode="json"),
        "page_number": page_number,
        "raw_bounding_box": raw_bounding_box.canonical_payload(),
        "raw_text_hash": raw_text_hash,
        "reading_order": reading_order,
        "source_output_artifact_digest": source_output_artifact_digest,
        "span_id": span_id,
    }
    return sha256(_canonical_json(payload)).hexdigest()


class BoundingBox(DocumentContractModel):
    coordinate_system: CoordinateSystem
    left: Decimal
    top: Decimal
    right: Decimal
    bottom: Decimal

    @field_validator("left", "top", "right", "bottom")
    @classmethod
    def coordinate_is_fixed_point(cls, value: Decimal) -> Decimal:
        if not value.is_finite():
            raise ValueError("bounding box coordinates must be finite")
        if abs(value) > _MAX_COORDINATE:
            raise ValueError("bounding box coordinate exceeds the supported range")
        try:
            fixed = value.quantize(_COORDINATE_QUANTUM)
        except InvalidOperation as error:
            raise ValueError("bounding box coordinate has invalid precision") from error
        if fixed != value:
            raise ValueError("bounding box coordinates support at most six decimal places")
        if fixed.is_zero():
            return Decimal("0.000000")
        return fixed

    @model_validator(mode="after")
    def ordered_coordinates(self) -> Self:
        if self.left >= self.right:
            raise ValueError("bounding box left must be less than right")
        if self.coordinate_system is CoordinateSystem.NORMALIZED_TOP_LEFT:
            coordinates = (self.left, self.top, self.right, self.bottom)
            if not all(Decimal(0) <= value <= Decimal(1) for value in coordinates):
                raise ValueError("normalized bounding box coordinates must be within [0, 1]")
            if self.top >= self.bottom:
                raise ValueError("bounding box top must be less than bottom")
        elif self.bottom >= self.top:
            raise ValueError("PDF bounding box bottom must be less than top")
        return self

    def canonical_payload(self) -> dict[str, str]:
        return {
            "bottom": _fixed_decimal(self.bottom),
            "coordinate_system": self.coordinate_system.value,
            "left": _fixed_decimal(self.left),
            "right": _fixed_decimal(self.right),
            "top": _fixed_decimal(self.top),
        }


class PageGeometry(DocumentContractModel):
    page_number: StrictInt = Field(ge=1, le=2_000)
    media_box: BoundingBox
    crop_box: BoundingBox
    rotation_degrees: Literal[0, 90, 180, 270]

    @model_validator(mode="after")
    def geometry_has_valid_pdf_boxes(self) -> Self:
        if self.media_box.coordinate_system is not CoordinateSystem.PDF_BOTTOM_LEFT_POINTS:
            raise ValueError("media_box must use PDF point coordinates")
        if self.crop_box.coordinate_system is not CoordinateSystem.PDF_BOTTOM_LEFT_POINTS:
            raise ValueError("crop_box must use PDF point coordinates")
        if not (
            self.media_box.left <= self.crop_box.left < self.crop_box.right <= self.media_box.right
            and self.media_box.bottom
            <= self.crop_box.bottom
            < self.crop_box.top
            <= self.media_box.top
        ):
            raise ValueError("crop_box must be contained within media_box")
        return self

    @property
    def width_points(self) -> Decimal:
        return self.crop_box.right - self.crop_box.left

    @property
    def height_points(self) -> Decimal:
        return self.crop_box.top - self.crop_box.bottom


class _WorkerIdentity(DocumentContractModel):
    name: str = Field(min_length=1, max_length=80, pattern=r"^[A-Za-z0-9][A-Za-z0-9 ._+-]{0,79}$")
    version: str = Field(pattern=_VERSION_PATTERN)
    build_hash: str = Field(pattern=_SHA256_PATTERN)
    configuration_hash: str = Field(pattern=_SHA256_PATTERN)


class DocumentProfilerIdentity(_WorkerIdentity):
    schema_version: Literal["1.0.0"] = "1.0.0"
    profiler_id: str = Field(pattern=_IDENTIFIER_PATTERN)


class ParserCandidateIdentity(_WorkerIdentity):
    schema_version: Literal["1.0.0"] = "1.0.0"
    parser_id: str = Field(pattern=_IDENTIFIER_PATTERN)
    tier: StrictInt = Field(ge=0, le=4)


class GovernanceRecordReference(DocumentContractModel):
    schema_version: Literal["1.0.0"] = "1.0.0"
    record_id: str = Field(pattern=_GOVERNANCE_RECORD_PATTERN)
    record_hash: str = Field(pattern=_SHA256_PATTERN)

    @model_validator(mode="after")
    def reference_is_content_addressed(self) -> Self:
        if self.record_id != f"governance:{self.record_hash}":
            raise ValueError("governance record_id must match record_hash")
        return self


class GovernanceApprovalRecord(DocumentContractModel):
    schema_version: Literal["1.0.0"] = "1.0.0"
    record_id: str = Field(pattern=_GOVERNANCE_RECORD_PATTERN)
    record_hash: str = Field(pattern=_SHA256_PATTERN)
    subject_kind: GovernanceSubjectKind
    subject_id: str = Field(pattern=_IDENTIFIER_PATTERN)
    subject_build_hash: str = Field(pattern=_SHA256_PATTERN)
    subject_configuration_hash: str = Field(pattern=_SHA256_PATTERN)
    policy_version: str = Field(pattern=_VERSION_PATTERN)
    benchmark_hash: str = Field(pattern=_SHA256_PATTERN)
    approved_by: UUID
    approved_at: datetime

    @field_validator("approved_at")
    @classmethod
    def approved_at_is_utc(cls, value: datetime) -> datetime:
        return _require_utc(value, field_name="approved_at")

    @model_validator(mode="after")
    def record_identity_is_content_addressed(self) -> Self:
        expected_hash = _governance_record_hash(self)
        if self.record_hash != expected_hash or self.record_id != f"governance:{expected_hash}":
            raise ValueError("governance record identity must match immutable record content")
        if self.policy_version.startswith("phase-2a-"):
            raise ValueError("governance policy cannot reuse a Phase 2A admission policy")
        return self

    def reference(self) -> GovernanceRecordReference:
        return GovernanceRecordReference(record_id=self.record_id, record_hash=self.record_hash)

    def matches_profiler(self, profiler: DocumentProfilerIdentity) -> bool:
        return (
            self.subject_kind is GovernanceSubjectKind.PROFILER
            and self.subject_id == profiler.profiler_id
            and self.subject_build_hash == profiler.build_hash
            and self.subject_configuration_hash == profiler.configuration_hash
        )

    def matches_parser(self, parser: ParserCandidateIdentity) -> bool:
        return (
            self.subject_kind is GovernanceSubjectKind.PARSER
            and self.subject_id == parser.parser_id
            and self.subject_build_hash == parser.build_hash
            and self.subject_configuration_hash == parser.configuration_hash
        )


def build_governance_approval_record(
    *,
    subject_kind: GovernanceSubjectKind,
    subject_id: str,
    subject_build_hash: str,
    subject_configuration_hash: str,
    policy_version: str,
    benchmark_hash: str,
    approved_by: UUID,
    approved_at: datetime,
) -> GovernanceApprovalRecord:
    payload = {
        "approved_at": approved_at.isoformat(),
        "approved_by": str(approved_by),
        "benchmark_hash": benchmark_hash,
        "policy_version": policy_version,
        "schema_version": "1.0.0",
        "subject_build_hash": subject_build_hash,
        "subject_configuration_hash": subject_configuration_hash,
        "subject_id": subject_id,
        "subject_kind": subject_kind.value,
    }
    record_hash = sha256(_canonical_json(payload)).hexdigest()
    return GovernanceApprovalRecord(
        record_id=f"governance:{record_hash}",
        record_hash=record_hash,
        subject_kind=subject_kind,
        subject_id=subject_id,
        subject_build_hash=subject_build_hash,
        subject_configuration_hash=subject_configuration_hash,
        policy_version=policy_version,
        benchmark_hash=benchmark_hash,
        approved_by=approved_by,
        approved_at=approved_at,
    )


class DocumentPreflightProfile(DocumentContractModel):
    schema_version: Literal["1.0.0"] = "1.0.0"
    preflight_run_id: UUID
    context: ArtifactCommandContext
    acquisition_id: UUID
    artifact: ArtifactDescriptor
    profiler: DocumentProfilerIdentity
    page_count: StrictInt | None = Field(default=None, ge=1, le=2_000)
    pages: tuple[PageGeometry, ...] = Field(max_length=2_000)
    encryption_password_state: SafetyCheckState
    malformed_structure: SafetyCheckState
    embedded_files: SafetyCheckState
    active_actions: SafetyCheckState
    suspicious_references: SafetyCheckState
    decompression_ratio: SafetyCheckState
    decoded_stream_bytes: StrictInt = Field(ge=0, le=1_073_741_824)
    character_count: StrictInt = Field(ge=0, le=100_000_000)
    image_only_page_count: StrictInt | None = Field(default=None, ge=0, le=2_000)
    warnings: tuple[str, ...] = Field(max_length=128)
    profiled_at: datetime

    @field_validator("warnings")
    @classmethod
    def warnings_are_canonical(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        return _canonical_codes(value, field_name="warnings")

    @field_validator("profiled_at")
    @classmethod
    def profiled_at_is_utc(cls, value: datetime) -> datetime:
        return _require_utc(value, field_name="profiled_at")

    @model_validator(mode="after")
    def profile_is_bound_and_complete(self) -> Self:
        _require_pdf_artifact(self.artifact)
        if self.page_count is None:
            if self.pages:
                raise ValueError("preflight pages require an authoritative page_count")
            if self.image_only_page_count is not None:
                raise ValueError("image_only_page_count requires an authoritative page_count")
            return self
        _require_exact_pages(self.pages, self.page_count, field_name="preflight pages")
        if self.image_only_page_count is None:
            raise ValueError("known page_count requires image_only_page_count evidence")
        if self.image_only_page_count > self.page_count:
            raise ValueError("image_only_page_count cannot exceed page_count")
        return self

    def has_authoritative_accept_evidence(self) -> bool:
        mandatory = (
            self.encryption_password_state,
            self.malformed_structure,
            self.embedded_files,
            self.active_actions,
            self.suspicious_references,
            self.decompression_ratio,
        )
        return (
            self.page_count is not None
            and self.image_only_page_count is not None
            and all(state is SafetyCheckState.PASS for state in mandatory)
        )


class AdmissionAssessmentDraft(DocumentContractModel):
    schema_version: Literal["1.0.0"] = "1.0.0"
    policy_version: Literal["phase-2b-preflight-1"] = "phase-2b-preflight-1"
    assessment_id: UUID
    context: ArtifactCommandContext
    acquisition_id: UUID
    artifact: ArtifactDescriptor
    prior_admission_hash: str = Field(pattern=_SHA256_PATTERN)
    preflight: DocumentPreflightProfile
    promotion: GovernanceRecordReference | None
    lifecycle: DocumentProcessingLifecycle
    outcome: AdmissionOutcome
    reason_codes: tuple[str, ...] = Field(min_length=1, max_length=32)
    assessed_at: datetime

    @field_validator("reason_codes")
    @classmethod
    def reasons_are_canonical(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        return _canonical_codes(value, field_name="reason codes")

    @field_validator("assessed_at")
    @classmethod
    def assessed_at_is_utc(cls, value: datetime) -> datetime:
        return _require_utc(value, field_name="assessed_at")

    @model_validator(mode="after")
    def draft_lifecycle_is_consistent(self) -> Self:
        accepted = self.outcome in {
            AdmissionOutcome.ACCEPT,
            AdmissionOutcome.ACCEPT_WITH_RESTRICTIONS,
        }
        if accepted and self.lifecycle is not DocumentProcessingLifecycle.PREFLIGHTED:
            raise ValueError("accepted assessment lifecycle must be preflighted")
        if not accepted:
            allowed = {
                AdmissionOutcome.QUARANTINE_FOR_REVIEW: DocumentProcessingLifecycle.AWAITING_REVIEW,
                AdmissionOutcome.REQUEST_PASSWORD: DocumentProcessingLifecycle.AWAITING_PASSWORD,
                AdmissionOutcome.REJECT_POLICY_VIOLATION: (
                    DocumentProcessingLifecycle.FAILED_TERMINAL
                ),
                AdmissionOutcome.REJECT_UNSAFE: DocumentProcessingLifecycle.FAILED_TERMINAL,
            }
            expected = allowed.get(self.outcome)
            if expected is None:
                raise ValueError("Phase 2B assessment outcome is not supported")
            if self.lifecycle is not expected:
                raise ValueError("assessment lifecycle is inconsistent with the outcome")
        return self


@dataclass(frozen=True)
class _ResolvedAssessmentAuthority:
    prior_admission: DocumentAdmissionRecord
    promotion: GovernanceApprovalRecord | None


class AdmissionAssessment(AdmissionAssessmentDraft):
    authority: _ResolvedAssessmentAuthority = Field(exclude=True, repr=False)

    @classmethod
    def from_resolved_records(
        cls,
        draft: AdmissionAssessmentDraft,
        *,
        prior_admission: DocumentAdmissionRecord,
        promotion: GovernanceApprovalRecord | None,
    ) -> AdmissionAssessment:
        return cls(
            **draft.__dict__,
            authority=_ResolvedAssessmentAuthority(
                prior_admission=prior_admission,
                promotion=promotion,
            ),
        )

    @model_validator(mode="after")
    def assessment_is_authorized_and_bound(self) -> Self:
        self._validate_prior_admission(self.authority.prior_admission)
        if self.context.workspace_id != self.preflight.context.workspace_id:
            raise ValueError("assessment workspace does not match preflight workspace")
        if self.context.tenant_id != self.preflight.context.tenant_id:
            raise ValueError("assessment tenant does not match preflight tenant")
        if self.acquisition_id != self.preflight.acquisition_id:
            raise ValueError("assessment acquisition does not match preflight acquisition")
        if self.artifact != self.preflight.artifact:
            raise ValueError("assessment artifact does not match preflight artifact")

        accepted = self.outcome in {
            AdmissionOutcome.ACCEPT,
            AdmissionOutcome.ACCEPT_WITH_RESTRICTIONS,
        }
        if accepted:
            if self.lifecycle is not DocumentProcessingLifecycle.PREFLIGHTED:
                raise ValueError("accepted assessment lifecycle must be preflighted")
            resolved_promotion = self.authority.promotion
            if (
                self.promotion is None
                or resolved_promotion is None
                or resolved_promotion.reference() != self.promotion
                or not resolved_promotion.matches_profiler(self.preflight.profiler)
            ):
                raise ValueError("accepted assessment requires the resolved profiler promotion")
            if not self.preflight.has_authoritative_accept_evidence():
                raise ValueError("accepted assessment requires authoritative preflight evidence")
        return self

    def _validate_prior_admission(self, prior: DocumentAdmissionRecord) -> None:
        if prior.context.tenant_id != self.context.tenant_id:
            raise ValueError("prior admission tenant does not match assessment tenant")
        if prior.context.workspace_id != self.context.workspace_id:
            raise ValueError("prior admission workspace does not match assessment workspace")
        if prior.request.acquisition_id != self.acquisition_id:
            raise ValueError("prior admission acquisition does not match assessment acquisition")
        if prior.artifact != self.artifact:
            raise ValueError("prior admission artifact does not match assessment artifact")
        if self.prior_admission_hash != document_admission_record_hash(prior):
            raise ValueError("prior admission hash does not match the immutable admission record")
        if (
            prior.lifecycle is not DocumentLifecycle.AWAITING_REVIEW
            or prior.outcome is not AdmissionOutcome.QUARANTINE_FOR_REVIEW
        ):
            raise ValueError("prior admission is not eligible for Phase 2B reassessment")
        hard_checks = (
            prior.profile.mime_signature_consistency,
            prior.profile.size_limit,
            prior.profile.source_policy,
            prior.profile.available_disk,
        )
        if any(state is not SafetyCheckState.PASS for state in hard_checks):
            raise ValueError("prior admission hard checks do not permit reassessment")


class ParserRunRequest(DocumentContractModel):
    schema_version: Literal["1.0.0"] = "1.0.0"
    parser_run_id: UUID
    context: ArtifactCommandContext
    acquisition_id: UUID
    artifact: ArtifactDescriptor
    candidate: ParserCandidateIdentity
    page_numbers: tuple[StrictInt, ...] = Field(min_length=1, max_length=2_000)
    maximum_output_bytes: StrictInt = Field(ge=1_024, le=268_435_456)

    @field_validator("page_numbers")
    @classmethod
    def page_numbers_are_canonical(cls, value: tuple[int, ...]) -> tuple[int, ...]:
        if any(number < 1 or number > 2_000 for number in value):
            raise ValueError("page numbers must be between 1 and 2000")
        if tuple(sorted(set(value))) != value:
            raise ValueError("page numbers must be unique and sorted")
        return value

    @model_validator(mode="after")
    def request_uses_pdf_artifact(self) -> Self:
        _require_pdf_artifact(self.artifact)
        return self


class ParserSpan(DocumentContractModel):
    schema_version: Literal["1.0.0"] = "1.0.0"
    span_id: str = Field(pattern=r"^span_[a-z0-9_]{1,58}$")
    page_number: StrictInt = Field(ge=1, le=2_000)
    reading_order: StrictInt = Field(ge=0, le=1_000_000)
    bounding_box: BoundingBox
    raw_text: str = Field(max_length=2_000_000)
    raw_text_hash: str = Field(pattern=_SHA256_PATTERN)
    normalized_text: str = Field(max_length=2_000_000)
    normalized_text_hash: str = Field(pattern=_SHA256_PATTERN)
    font_name: str | None = Field(default=None, max_length=255)
    font_size_points: Decimal | None = Field(default=None, gt=0, le=10_000)
    warnings: tuple[str, ...] = Field(max_length=64)

    @field_validator("warnings")
    @classmethod
    def warnings_are_canonical(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        return _canonical_codes(value, field_name="warnings")

    @model_validator(mode="after")
    def span_content_is_exact(self) -> Self:
        if self.bounding_box.coordinate_system is not CoordinateSystem.PDF_BOTTOM_LEFT_POINTS:
            raise ValueError("parser span bounding box must retain PDF coordinates")
        _require_text(self.raw_text, field_name="raw_text", require_nfc=False)
        _require_text(self.normalized_text, field_name="normalized_text", require_nfc=True)
        if self.raw_text_hash != sha256_text(self.raw_text):
            raise ValueError("raw_text_hash does not match raw_text")
        if self.normalized_text_hash != sha256_text(self.normalized_text):
            raise ValueError("normalized_text_hash does not match normalized_text")
        return self


class ParserCandidatePage(DocumentContractModel):
    schema_version: Literal["1.0.0"] = "1.0.0"
    page_number: StrictInt = Field(ge=1, le=2_000)
    geometry: PageGeometry
    spans: tuple[ParserSpan, ...] = Field(max_length=1_000_000)
    image_count: StrictInt = Field(ge=0, le=1_000_000)
    warnings: tuple[str, ...] = Field(max_length=128)

    @field_validator("warnings")
    @classmethod
    def warnings_are_canonical(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        return _canonical_codes(value, field_name="warnings")

    @model_validator(mode="after")
    def page_content_is_bound(self) -> Self:
        if self.geometry.page_number != self.page_number:
            raise ValueError("page geometry does not match page number")
        if any(span.page_number != self.page_number for span in self.spans):
            raise ValueError("parser span page does not match candidate page")
        orders = tuple(span.reading_order for span in self.spans)
        if tuple(sorted(set(orders))) != orders:
            raise ValueError("span reading order must be unique and sorted")
        identifiers = tuple(span.span_id for span in self.spans)
        if len(set(identifiers)) != len(identifiers):
            raise ValueError("span identifiers must be unique")
        return self


class ParserRunResult(DocumentContractModel):
    schema_version: Literal["1.0.0"] = "1.0.0"
    request: ParserRunRequest
    status: ParserRunStatus
    pages: tuple[ParserCandidatePage, ...] = Field(max_length=2_000)
    output_artifact: ArtifactDescriptor | None
    warnings: tuple[str, ...] = Field(max_length=128)
    started_at: datetime
    finished_at: datetime

    @field_validator("warnings")
    @classmethod
    def warnings_are_canonical(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        return _canonical_codes(value, field_name="warnings")

    @field_validator("started_at", "finished_at")
    @classmethod
    def timestamps_are_utc(cls, value: datetime, info: object) -> datetime:
        field_name = getattr(info, "field_name", "timestamp")
        return _require_utc(value, field_name=field_name)

    @model_validator(mode="after")
    def result_is_terminal_and_bound(self) -> Self:
        if self.finished_at < self.started_at:
            raise ValueError("finished_at cannot precede started_at")
        if self.status is ParserRunStatus.SUCCEEDED:
            if self.output_artifact is None:
                raise ValueError("successful parser result requires output artifact")
            if self.output_artifact.media_type != "application/vnd.rsi-atlas.parser-result+json":
                raise ValueError("parser output artifact has an invalid media type")
            page_numbers = tuple(page.page_number for page in self.pages)
            if page_numbers != self.request.page_numbers:
                raise ValueError("parser result pages do not match requested pages")
            if not 1 <= self.output_artifact.size_bytes <= self.request.maximum_output_bytes:
                raise ValueError("parser output size exceeds the bounded request")
        elif self.pages or self.output_artifact is not None:
            raise ValueError("failed parser result cannot expose pages or output artifact")
        return self


class ParserQualityReport(DocumentContractModel):
    schema_version: Literal["1.0.0"] = "1.0.0"
    parser_run_id: UUID
    candidate: ParserCandidateIdentity
    page_count: StrictInt = Field(ge=1, le=2_000)
    pages_with_content: StrictInt = Field(ge=0, le=2_000)
    page_coverage: StrictFloat = Field(ge=0.0, le=1.0)
    replacement_character_rate: StrictFloat = Field(ge=0.0, le=1.0)
    crypto_token_preservation_rate: StrictFloat = Field(ge=0.0, le=1.0)
    valid_bounding_box_rate: StrictFloat = Field(ge=0.0, le=1.0)
    deterministic_output_hash: str = Field(pattern=_SHA256_PATTERN)
    decision: ParserQualityDecision
    warnings: tuple[str, ...] = Field(max_length=128)
    evaluated_at: datetime

    @field_validator("warnings")
    @classmethod
    def warnings_are_canonical(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        return _canonical_codes(value, field_name="warnings")

    @field_validator("evaluated_at")
    @classmethod
    def evaluated_at_is_utc(cls, value: datetime) -> datetime:
        return _require_utc(value, field_name="evaluated_at")

    @model_validator(mode="after")
    def metrics_are_consistent(self) -> Self:
        if self.pages_with_content > self.page_count:
            raise ValueError("pages_with_content cannot exceed page_count")
        expected_coverage = self.pages_with_content / self.page_count
        if abs(self.page_coverage - expected_coverage) > 1e-12:
            raise ValueError("page_coverage must match page counts")
        return self


class ParserSpanProvenance(DocumentContractModel):
    schema_version: Literal["1.0.0"] = "1.0.0"
    source_output_artifact_digest: str = Field(pattern=_SHA256_PATTERN)
    candidate: ParserCandidateIdentity
    span_id: str = Field(pattern=r"^span_[a-z0-9_]{1,58}$")
    page_number: StrictInt = Field(ge=1, le=2_000)
    reading_order: StrictInt = Field(ge=0, le=1_000_000)
    raw_bounding_box: BoundingBox
    raw_text_hash: str = Field(pattern=_SHA256_PATTERN)
    source_span_hash: str = Field(pattern=_SHA256_PATTERN)

    @model_validator(mode="after")
    def provenance_is_content_addressed(self) -> Self:
        if self.raw_bounding_box.coordinate_system is not CoordinateSystem.PDF_BOTTOM_LEFT_POINTS:
            raise ValueError("source span provenance must retain PDF coordinates")
        expected = parser_span_source_hash(
            source_output_artifact_digest=self.source_output_artifact_digest,
            candidate=self.candidate,
            span_id=self.span_id,
            page_number=self.page_number,
            reading_order=self.reading_order,
            raw_bounding_box=self.raw_bounding_box,
            raw_text_hash=self.raw_text_hash,
        )
        if self.source_span_hash != expected:
            raise ValueError("source_span_hash does not match retained parser span evidence")
        return self


class ParserRunReference(DocumentContractModel):
    schema_version: Literal["1.0.0"] = "1.0.0"
    reference_id: str = Field(pattern=_RUN_REFERENCE_PATTERN)
    parser_run_id: UUID
    context: ArtifactCommandContext
    acquisition_id: UUID
    input_artifact: ArtifactDescriptor
    candidate: ParserCandidateIdentity
    output_artifact: ArtifactDescriptor
    result_hash: str = Field(pattern=_SHA256_PATTERN)
    spans: tuple[ParserSpanProvenance, ...] = Field(max_length=2_000_000)
    completed_at: datetime

    @field_validator("completed_at")
    @classmethod
    def completed_at_is_utc(cls, value: datetime) -> datetime:
        return _require_utc(value, field_name="completed_at")

    @model_validator(mode="after")
    def reference_is_content_addressed(self) -> Self:
        _require_pdf_artifact(self.input_artifact)
        if self.output_artifact.media_type != "application/vnd.rsi-atlas.parser-result+json":
            raise ValueError("parser run reference output has an invalid media type")
        span_keys: set[tuple[int, str]] = set()
        for span in self.spans:
            if span.source_output_artifact_digest != self.output_artifact.digest:
                raise ValueError("parser span provenance references another output artifact")
            if span.candidate != self.candidate:
                raise ValueError("parser span provenance references another candidate")
            key = (span.page_number, span.span_id)
            if key in span_keys:
                raise ValueError("parser span provenance identifiers must be unique per page")
            span_keys.add(key)
        expected = _parser_run_reference_id(
            parser_run_id=self.parser_run_id,
            context=self.context,
            acquisition_id=self.acquisition_id,
            input_artifact=self.input_artifact,
            candidate=self.candidate,
            output_artifact=self.output_artifact,
            result_hash=self.result_hash,
            spans=self.spans,
            completed_at=self.completed_at,
        )
        if self.reference_id != expected:
            raise ValueError("parser run reference_id does not match retained run evidence")
        return self

    @classmethod
    def from_result(cls, result: ParserRunResult) -> ParserRunReference:
        if result.status is not ParserRunStatus.SUCCEEDED or result.output_artifact is None:
            raise ValueError("only a successful parser result can create a run reference")
        result_hash = sha256(result.canonical_json_bytes()).hexdigest()
        spans = tuple(
            ParserSpanProvenance(
                source_output_artifact_digest=result.output_artifact.digest,
                candidate=result.request.candidate,
                span_id=span.span_id,
                page_number=span.page_number,
                reading_order=span.reading_order,
                raw_bounding_box=span.bounding_box,
                raw_text_hash=span.raw_text_hash,
                source_span_hash=parser_span_source_hash(
                    source_output_artifact_digest=result.output_artifact.digest,
                    candidate=result.request.candidate,
                    span_id=span.span_id,
                    page_number=span.page_number,
                    reading_order=span.reading_order,
                    raw_bounding_box=span.bounding_box,
                    raw_text_hash=span.raw_text_hash,
                ),
            )
            for page in result.pages
            for span in page.spans
        )
        reference_id = _parser_run_reference_id(
            parser_run_id=result.request.parser_run_id,
            context=result.request.context,
            acquisition_id=result.request.acquisition_id,
            input_artifact=result.request.artifact,
            candidate=result.request.candidate,
            output_artifact=result.output_artifact,
            result_hash=result_hash,
            spans=spans,
            completed_at=result.finished_at,
        )
        return cls(
            reference_id=reference_id,
            parser_run_id=result.request.parser_run_id,
            context=result.request.context,
            acquisition_id=result.request.acquisition_id,
            input_artifact=result.request.artifact,
            candidate=result.request.candidate,
            output_artifact=result.output_artifact,
            result_hash=result_hash,
            spans=spans,
            completed_at=result.finished_at,
        )


class _CanonicalElementBase(DocumentContractModel):
    kind: str
    canonicalization_id: str = Field(pattern=_CANONICALIZATION_KEY_PATTERN)
    element_id: str = Field(pattern=_ELEMENT_ID_PATTERN)
    page_number: StrictInt = Field(ge=1, le=2_000)
    reading_order: StrictInt = Field(ge=0, le=1_000_000)
    bounding_box: BoundingBox
    raw_bounding_box: BoundingBox
    raw_text: str = Field(max_length=2_000_000)
    raw_text_hash: str = Field(pattern=_SHA256_PATTERN)
    normalized_text: str = Field(max_length=2_000_000)
    normalized_text_hash: str = Field(pattern=_SHA256_PATTERN)
    parent_section_id: str | None = Field(default=None, pattern=r"^section:[0-9a-f]{64}$")
    parser_confidence: StrictFloat = Field(ge=0.0, le=1.0)
    ocr_confidence: StrictFloat | None = Field(default=None, ge=0.0, le=1.0)
    language: str = Field(pattern=r"^(unknown|[a-z]{2,3}(?:-[a-z0-9]{2,8})*)$")
    source_output_artifact_digest: str = Field(pattern=_SHA256_PATTERN)
    source_span_id: str = Field(pattern=r"^span_[a-z0-9_]{1,58}$")
    source_span_hash: str = Field(pattern=_SHA256_PATTERN)
    source_hash: str = Field(pattern=_SHA256_PATTERN)

    @model_validator(mode="after")
    def element_lineage_is_exact(self) -> Self:
        if self.bounding_box.coordinate_system is not CoordinateSystem.NORMALIZED_TOP_LEFT:
            raise ValueError("canonical bounding box must use normalized top-left coordinates")
        if self.raw_bounding_box.coordinate_system is not CoordinateSystem.PDF_BOTTOM_LEFT_POINTS:
            raise ValueError("raw bounding box must retain PDF coordinates")
        _require_text(self.raw_text, field_name="raw_text", require_nfc=False)
        _require_text(self.normalized_text, field_name="normalized_text", require_nfc=True)
        if self.raw_text_hash != sha256_text(self.raw_text):
            raise ValueError("raw_text_hash does not match raw_text")
        if self.normalized_text_hash != sha256_text(self.normalized_text):
            raise ValueError("normalized_text_hash does not match normalized_text")
        if self.source_hash != self.source_span_hash:
            raise ValueError("source_hash must bind the retained parser span")
        expected = canonical_element_identifier(
            canonicalization_id=self.canonicalization_id,
            page_number=self.page_number,
            kind=self.kind,
            reading_order=self.reading_order,
            bounding_box=self.bounding_box,
            raw_text_hash=self.raw_text_hash,
        )
        if self.element_id != expected:
            raise ValueError("element_id does not match deterministic element identity")
        return self


class CanonicalTextElement(_CanonicalElementBase):
    kind: Literal["text"]
    role: CanonicalTextRole


class CanonicalTableElement(_CanonicalElementBase):
    kind: Literal["table"]
    row_count: StrictInt = Field(ge=1, le=100_000)
    column_count: StrictInt = Field(ge=1, le=10_000)


class CanonicalFigureElement(_CanonicalElementBase):
    kind: Literal["figure"]
    image_artifact_id: ArtifactID | None = Field(default=None, pattern=r"^sha256:[0-9a-f]{64}$")
    caption_element_id: str | None = Field(default=None, pattern=_ELEMENT_ID_PATTERN)


CanonicalElement = Annotated[
    CanonicalTextElement | CanonicalTableElement | CanonicalFigureElement,
    Field(discriminator="kind"),
]


class CanonicalPage(DocumentContractModel):
    schema_version: Literal["1.0.0"] = "1.0.0"
    canonicalization_id: str = Field(pattern=_CANONICALIZATION_KEY_PATTERN)
    source_artifact_digest: str = Field(pattern=_SHA256_PATTERN)
    page_number: StrictInt = Field(ge=1, le=2_000)
    geometry: PageGeometry
    elements: tuple[CanonicalElement, ...] = Field(min_length=1, max_length=1_000_000)

    @model_validator(mode="after")
    def page_elements_are_bound(self) -> Self:
        if self.geometry.page_number != self.page_number:
            raise ValueError("canonical page geometry does not match page number")
        orders: list[int] = []
        identifiers: list[str] = []
        for element in self.elements:
            if element.page_number != self.page_number:
                raise ValueError("canonical element page does not match canonical page")
            if element.canonicalization_id != self.canonicalization_id:
                raise ValueError("canonical element uses another canonicalization identity")
            if not _box_contains(self.geometry.crop_box, element.raw_bounding_box):
                raise ValueError("canonical element raw box falls outside the page crop_box")
            orders.append(element.reading_order)
            identifiers.append(element.element_id)
        if tuple(sorted(set(orders))) != tuple(orders):
            raise ValueError("canonical element reading order must be unique and sorted")
        if len(set(identifiers)) != len(identifiers):
            raise ValueError("canonical element identifiers must be unique")
        return self


class CanonicalDocument(DocumentContractModel):
    schema_version: Literal["1.0.0"] = "1.0.0"
    canonicalization_id: str = Field(pattern=_CANONICALIZATION_KEY_PATTERN)
    source_artifact_digest: str = Field(pattern=_SHA256_PATTERN)
    candidate: ParserCandidateIdentity
    normalizer_version: str = Field(pattern=_VERSION_PATTERN)
    normalizer_configuration_hash: str = Field(pattern=_SHA256_PATTERN)
    pages: tuple[CanonicalPage, ...] = Field(min_length=1, max_length=2_000)

    @model_validator(mode="after")
    def content_identity_is_exact(self) -> Self:
        expected_key = canonicalization_identifier(
            artifact_digest=self.source_artifact_digest,
            parser_build_hash=self.candidate.build_hash,
            parser_configuration_hash=self.candidate.configuration_hash,
            normalizer_version=self.normalizer_version,
            normalizer_configuration_hash=self.normalizer_configuration_hash,
        )
        if self.canonicalization_id != expected_key:
            raise ValueError("canonicalization_id does not match source and configuration")
        _require_exact_pages(self.pages, len(self.pages), field_name="canonical pages")
        for page in self.pages:
            if page.canonicalization_id != self.canonicalization_id:
                raise ValueError("canonical page uses another canonicalization identity")
            if page.source_artifact_digest != self.source_artifact_digest:
                raise ValueError("canonical page references another source artifact")
        return self


class CanonicalDocumentManifestDraft(DocumentContractModel):
    schema_version: Literal["1.0.0"] = "1.0.0"
    manifest_id: UUID
    context: ArtifactCommandContext
    acquisition_id: UUID
    artifact: ArtifactDescriptor
    source_run: ParserRunReference
    quality: ParserQualityReport
    qualification: GovernanceRecordReference
    canonical_document: CanonicalDocument
    document_version_id: str = Field(pattern=_CANONICAL_ID_PATTERN)
    canonical_content_hash: str = Field(pattern=_SHA256_PATTERN)
    canonical_artifact: ArtifactDescriptor
    lifecycle: Literal[DocumentProcessingLifecycle.CANONICALIZED]
    recorded_at: datetime

    @field_validator("recorded_at")
    @classmethod
    def recorded_at_is_utc(cls, value: datetime) -> datetime:
        return _require_utc(value, field_name="recorded_at")


@dataclass(frozen=True)
class _ResolvedCanonicalAuthority:
    qualification: GovernanceApprovalRecord


class CanonicalDocumentManifest(CanonicalDocumentManifestDraft):
    authority: _ResolvedCanonicalAuthority = Field(exclude=True, repr=False)

    @classmethod
    def from_resolved_record(
        cls,
        draft: CanonicalDocumentManifestDraft,
        *,
        qualification_record: GovernanceApprovalRecord,
    ) -> CanonicalDocumentManifest:
        return cls(
            **draft.__dict__,
            authority=_ResolvedCanonicalAuthority(qualification=qualification_record),
        )

    @model_validator(mode="after")
    def manifest_is_authorized_and_bound(self) -> Self:
        _require_pdf_artifact(self.artifact)
        run = self.source_run
        if run.context.tenant_id != self.context.tenant_id:
            raise ValueError("source parser run tenant does not match manifest")
        if run.context.workspace_id != self.context.workspace_id:
            raise ValueError("source parser run workspace does not match manifest")
        if run.acquisition_id != self.acquisition_id:
            raise ValueError("source parser run acquisition does not match manifest")
        if run.input_artifact != self.artifact:
            raise ValueError("source parser run artifact does not match manifest")
        if self.quality.parser_run_id != run.parser_run_id:
            raise ValueError("quality report references another parser run")
        if self.quality.candidate != run.candidate:
            raise ValueError("quality report references another parser candidate")
        if self.quality.deterministic_output_hash != run.output_artifact.digest:
            raise ValueError("quality report output hash does not match retained parser output")
        if self.quality.decision is not ParserQualityDecision.QUALIFIED:
            raise ValueError("canonicalization requires a qualified parser quality decision")
        resolved_qualification = self.authority.qualification
        if (
            resolved_qualification.reference() != self.qualification
            or not resolved_qualification.matches_parser(run.candidate)
        ):
            raise ValueError("canonicalization requires the resolved parser qualification")
        document = self.canonical_document
        if document.source_artifact_digest != self.artifact.digest:
            raise ValueError("canonical document references another source artifact")
        if document.candidate != run.candidate:
            raise ValueError("canonical document references another parser candidate")
        if len(document.pages) != self.quality.page_count:
            raise ValueError("canonical document page count does not match quality report")
        provenance = {(span.page_number, span.span_id): span for span in run.spans}
        for page in document.pages:
            for element in page.elements:
                source = provenance.get((element.page_number, element.source_span_id))
                if source is None:
                    raise ValueError("canonical element has no retained parser span provenance")
                if (
                    element.source_output_artifact_digest != source.source_output_artifact_digest
                    or element.source_span_hash != source.source_span_hash
                    or element.raw_text_hash != source.raw_text_hash
                    or element.raw_bounding_box != source.raw_bounding_box
                    or element.reading_order != source.reading_order
                ):
                    raise ValueError(
                        "canonical element does not match retained parser span evidence"
                    )
        expected_content_hash = sha256(document.canonical_json_bytes()).hexdigest()
        if self.canonical_content_hash != expected_content_hash:
            raise ValueError("canonical content hash does not match exact canonical bytes")
        if self.document_version_id != canonical_document_identifier(
            content_hash=expected_content_hash
        ):
            raise ValueError("document version does not match canonical content hash")
        if self.canonical_artifact.media_type != "application/vnd.rsi-atlas.canonical+json":
            raise ValueError("canonical artifact has an invalid media type")
        if self.canonical_artifact.digest != expected_content_hash:
            raise ValueError("canonical artifact digest does not match canonical content")
        if self.canonical_artifact.size_bytes != len(document.canonical_json_bytes()):
            raise ValueError("canonical artifact size does not match canonical content bytes")
        return self


def build_canonical_document(
    *,
    source_artifact_digest: str,
    candidate: ParserCandidateIdentity,
    normalizer_version: str,
    normalizer_configuration_hash: str,
    pages: tuple[CanonicalPage, ...],
) -> CanonicalDocument:
    canonicalization_id = canonicalization_identifier(
        artifact_digest=source_artifact_digest,
        parser_build_hash=candidate.build_hash,
        parser_configuration_hash=candidate.configuration_hash,
        normalizer_version=normalizer_version,
        normalizer_configuration_hash=normalizer_configuration_hash,
    )
    return CanonicalDocument(
        canonicalization_id=canonicalization_id,
        source_artifact_digest=source_artifact_digest,
        candidate=candidate,
        normalizer_version=normalizer_version,
        normalizer_configuration_hash=normalizer_configuration_hash,
        pages=pages,
    )


def _parser_run_reference_id(
    *,
    parser_run_id: UUID,
    context: ArtifactCommandContext,
    acquisition_id: UUID,
    input_artifact: ArtifactDescriptor,
    candidate: ParserCandidateIdentity,
    output_artifact: ArtifactDescriptor,
    result_hash: str,
    spans: tuple[ParserSpanProvenance, ...],
    completed_at: datetime,
) -> str:
    payload = {
        "acquisition_id": str(acquisition_id),
        "candidate": candidate.model_dump(mode="json"),
        "completed_at": completed_at.isoformat(),
        "context": context.model_dump(mode="json"),
        "input_artifact": input_artifact.model_dump(mode="json"),
        "output_artifact": output_artifact.model_dump(mode="json"),
        "parser_run_id": str(parser_run_id),
        "result_hash": result_hash,
        "spans": [span.model_dump(mode="json") for span in spans],
    }
    return f"parser-run:{sha256(_canonical_json(payload)).hexdigest()}"


def _governance_record_hash(record: GovernanceApprovalRecord) -> str:
    payload = {
        "approved_at": record.approved_at.isoformat(),
        "approved_by": str(record.approved_by),
        "benchmark_hash": record.benchmark_hash,
        "policy_version": record.policy_version,
        "schema_version": record.schema_version,
        "subject_build_hash": record.subject_build_hash,
        "subject_configuration_hash": record.subject_configuration_hash,
        "subject_id": record.subject_id,
        "subject_kind": record.subject_kind.value,
    }
    return sha256(_canonical_json(payload)).hexdigest()


def _canonical_json(value: object) -> bytes:
    return dumps(
        value,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def _fixed_decimal(value: Decimal) -> str:
    fixed = value.quantize(_COORDINATE_QUANTUM)
    if fixed.is_zero():
        fixed = Decimal("0.000000")
    return format(fixed, "f")


def _require_utc(value: datetime, *, field_name: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() != timedelta(0):
        raise ValueError(f"{field_name} must be timezone-aware UTC")
    return value


def _canonical_codes(value: tuple[str, ...], *, field_name: str) -> tuple[str, ...]:
    if any(
        not code
        or len(code) > 64
        or not code[0].isalpha()
        or code != code.casefold()
        or any(character not in "abcdefghijklmnopqrstuvwxyz0123456789_" for character in code)
        for code in value
    ):
        raise ValueError(f"{field_name} must contain lowercase identifiers")
    if tuple(sorted(set(value))) != value:
        raise ValueError(f"{field_name} must be unique and sorted")
    return value


def _require_text(value: str, *, field_name: str, require_nfc: bool) -> None:
    if require_nfc and normalize("NFC", value) != value:
        raise ValueError(f"{field_name} must use Unicode NFC")
    if any(
        category(character).startswith("C") and character not in _ALLOWED_TEXT_CONTROLS
        for character in value
    ):
        raise ValueError(f"{field_name} contains a forbidden control character")


def _require_pdf_artifact(artifact: ArtifactDescriptor) -> None:
    if artifact.media_type != "application/pdf":
        raise ValueError("document processing requires an application/pdf artifact")


def _require_exact_pages(
    pages: tuple[PageGeometry, ...] | tuple[CanonicalPage, ...],
    expected_count: int,
    *,
    field_name: str,
) -> None:
    numbers = tuple(page.page_number for page in pages)
    expected = tuple(range(1, expected_count + 1))
    if numbers != expected:
        raise ValueError(f"{field_name} must contain every page exactly once in order")


def _box_contains(outer: BoundingBox, inner: BoundingBox) -> bool:
    return (
        outer.coordinate_system is inner.coordinate_system
        and outer.left <= inner.left < inner.right <= outer.right
        and outer.bottom <= inner.bottom < inner.top <= outer.top
    )


__all__ = [
    "AdmissionAssessment",
    "AdmissionAssessmentDraft",
    "BoundingBox",
    "CanonicalDocument",
    "CanonicalDocumentManifest",
    "CanonicalDocumentManifestDraft",
    "CanonicalElement",
    "CanonicalFigureElement",
    "CanonicalPage",
    "CanonicalTableElement",
    "CanonicalTextElement",
    "CanonicalTextRole",
    "CoordinateSystem",
    "DocumentPreflightProfile",
    "DocumentProcessingLifecycle",
    "DocumentProfilerIdentity",
    "GovernanceApprovalRecord",
    "GovernanceRecordReference",
    "GovernanceSubjectKind",
    "PageGeometry",
    "ParserCandidateIdentity",
    "ParserCandidatePage",
    "ParserQualityDecision",
    "ParserQualityReport",
    "ParserRunReference",
    "ParserRunRequest",
    "ParserRunResult",
    "ParserRunStatus",
    "ParserSpan",
    "ParserSpanProvenance",
    "build_canonical_document",
    "build_governance_approval_record",
    "canonical_document_identifier",
    "canonical_element_identifier",
    "canonicalization_identifier",
    "document_admission_record_hash",
    "parser_span_source_hash",
    "sha256_text",
]
