"""CAS-then-manifest persistence for canonical PDF documents."""

from __future__ import annotations

import hashlib
import json
import unicodedata
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, Protocol
from uuid import UUID, uuid4

from rsi_atlas_contracts import (
    ArtifactCommandContext,
    ArtifactDescriptor,
    ArtifactIntegrityError,
    BoundingBox,
    CanonicalDocument,
    CanonicalDocumentManifest,
    CanonicalDocumentManifestDraft,
    CoordinateSystem,
    DocumentAdmissionRecord,
    DocumentProcessingLifecycle,
    GovernanceApprovalRecord,
    GovernanceSubjectKind,
    PageGeometry,
    ParserCandidateIdentity,
    ParserCandidatePage,
    ParserQualityDecision,
    ParserRunReference,
    ParserRunRequest,
    ParserRunResult,
    ParserRunStatus,
    ParserSpan,
    build_governance_approval_record,
    sha256_text,
)
from rsi_atlas_storage import ContentAddressedArtifactStore
from rsi_atlas_storage.artifact_repository import ArtifactRepository
from rsi_atlas_storage.document_processing_repository import DocumentProcessingRepository

from rsi_atlas_ingestion.canonicalization import (
    CanonicalizationError,
    build_quality_report,
    canonicalize_parse_result,
)
from rsi_atlas_ingestion.parser_service import _PARSER_CONFIG

_PARSER_BUILD_HASH = hashlib.sha256(b"pypdf-6.14.2-tier0-parse").hexdigest()
_PYPDF_CANDIDATE = ParserCandidateIdentity(
    parser_id="pypdf_tier0",
    name="pypdf",
    version="6.14.2",
    tier=0,
    build_hash=_PARSER_BUILD_HASH,
    configuration_hash=_PARSER_CONFIG,
)
_COORD_Q = Decimal("0.000001")


class AdmissionLookup(Protocol):
    def find(
        self, *, context: ArtifactCommandContext, acquisition_id: UUID
    ) -> DocumentAdmissionRecord | None: ...


def development_parser_qualification(
    *,
    approved_by: UUID,
    approved_at: datetime,
    benchmark_hash: str,
) -> GovernanceApprovalRecord:
    return build_governance_approval_record(
        subject_kind=GovernanceSubjectKind.PARSER,
        subject_id=_PYPDF_CANDIDATE.parser_id,
        subject_build_hash=_PYPDF_CANDIDATE.build_hash,
        subject_configuration_hash=_PYPDF_CANDIDATE.configuration_hash,
        policy_version="phase-2b-parser-dev-1",
        benchmark_hash=benchmark_hash,
        approved_by=approved_by,
        approved_at=approved_at,
    )


def _fixed(value: object) -> Decimal:
    quantized = Decimal(str(value)).quantize(_COORD_Q)
    if quantized.is_zero():
        return Decimal("0.000000")
    return quantized


def _pdf_box(payload: dict[str, Any]) -> BoundingBox:
    return BoundingBox(
        coordinate_system=CoordinateSystem.PDF_BOTTOM_LEFT_POINTS,
        left=_fixed(payload["left"]),
        bottom=_fixed(payload["bottom"]),
        right=_fixed(payload["right"]),
        top=_fixed(payload["top"]),
    )


def build_parser_run_result(
    *,
    context: ArtifactCommandContext,
    acquisition_id: UUID,
    artifact: ArtifactDescriptor,
    parse_result: dict[str, Any],
    output_artifact: ArtifactDescriptor,
    parser_run_id: UUID,
    started_at: datetime,
    finished_at: datetime,
) -> ParserRunResult:
    pages: list[ParserCandidatePage] = []
    for page in parse_result.get("pages") or []:
        media = page.get("media_box") or {
            "left": 0.0,
            "bottom": 0.0,
            "right": float(page["width"]),
            "top": float(page["height"]),
        }
        crop = page.get("crop_box") or media
        rotation = int(page.get("rotation_degrees") or 0)
        geometry = PageGeometry(
            page_number=int(page["page_number"]),
            media_box=_pdf_box(media),
            crop_box=_pdf_box(crop),
            rotation_degrees=rotation,  # type: ignore[arg-type]
        )
        spans: list[ParserSpan] = []
        for order, span in enumerate(page.get("spans") or []):
            raw = span.get("text") or ""
            if not raw.strip():
                continue
            normalized = unicodedata.normalize("NFC", raw)
            spans.append(
                ParserSpan(
                    span_id=f"span_{order:04d}",
                    page_number=geometry.page_number,
                    reading_order=order,
                    bounding_box=_pdf_box(span["source_box"]),
                    raw_text=raw,
                    raw_text_hash=sha256_text(raw),
                    normalized_text=normalized,
                    normalized_text_hash=sha256_text(normalized),
                    font_name=None,
                    font_size_points=None,
                    warnings=(),
                )
            )
        pages.append(
            ParserCandidatePage(
                page_number=geometry.page_number,
                geometry=geometry,
                spans=tuple(spans),
                image_count=0,
                warnings=(),
            )
        )
    request = ParserRunRequest(
        parser_run_id=parser_run_id,
        context=context,
        acquisition_id=acquisition_id,
        artifact=artifact,
        candidate=_PYPDF_CANDIDATE,
        page_numbers=tuple(page.page_number for page in pages),
        maximum_output_bytes=max(output_artifact.size_bytes, 1024),
    )
    return ParserRunResult(
        request=request,
        status=ParserRunStatus.SUCCEEDED,
        pages=tuple(pages),
        output_artifact=output_artifact,
        warnings=(),
        started_at=started_at,
        finished_at=finished_at,
    )


class CanonicalizationService:
    """Publish canonical JSON to CAS, then commit one append-only manifest."""

    def __init__(
        self,
        *,
        admissions: AdmissionLookup,
        processing: DocumentProcessingRepository,
        artifacts: ArtifactRepository,
        store: ContentAddressedArtifactStore,
    ) -> None:
        self._admissions = admissions
        self._processing = processing
        self._artifacts = artifacts
        self._store = store

    def canonicalize_and_persist(
        self,
        *,
        context: ArtifactCommandContext,
        acquisition_id: UUID,
        parse_attempt_id: UUID,
        parse_result: dict[str, Any],
        benchmark_hash: str,
        now: datetime | None = None,
    ) -> CanonicalDocumentManifest:
        recorded_at = now or datetime.now(UTC)
        admission = self._admissions.find(context=context, acquisition_id=acquisition_id)
        if admission is None:
            raise LookupError("acquisition admission record is missing")

        parser_payload = (
            json.dumps(parse_result, sort_keys=True, separators=(",", ":")) + "\n"
        ).encode()
        parser_descriptor = self._store.put_bytes(
            parser_payload,
            media_type="application/vnd.rsi-atlas.parser-result+json",
            context=context,
        )
        self._artifacts.register(context=context, descriptor=parser_descriptor)

        run_result = build_parser_run_result(
            context=context,
            acquisition_id=acquisition_id,
            artifact=admission.artifact,
            parse_result=parse_result,
            output_artifact=parser_descriptor,
            parser_run_id=parse_attempt_id,
            started_at=recorded_at,
            finished_at=recorded_at,
        )
        document, warnings = canonicalize_parse_result(
            parse_result=parse_result,
            source_artifact_digest=admission.artifact.digest,
            candidate=_PYPDF_CANDIDATE,
            source_output_artifact_digest=parser_descriptor.digest,
        )
        quality = build_quality_report(
            parser_run_id=parse_attempt_id,
            candidate=_PYPDF_CANDIDATE,
            document=document,
            parse_result=parse_result,
            deterministic_output_hash=parser_descriptor.digest,
            evaluated_at=recorded_at,
            warnings=warnings,
        )
        if quality.decision is not ParserQualityDecision.QUALIFIED:
            raise CanonicalizationError("quality_review_required")

        canonical_bytes = document.canonical_json_bytes()
        content_hash = hashlib.sha256(canonical_bytes).hexdigest()
        canonical_descriptor = self._store.put_bytes(
            canonical_bytes,
            media_type="application/vnd.rsi-atlas.canonical+json",
            context=context,
        )
        verified = self._store.verify(canonical_descriptor.artifact_id, context=context)
        if verified.digest != content_hash:
            raise CanonicalizationError("canonical_cas_digest_mismatch")
        self._artifacts.register(context=context, descriptor=canonical_descriptor)

        qualification = development_parser_qualification(
            approved_by=context.actor_id,
            approved_at=recorded_at,
            benchmark_hash=benchmark_hash,
        )
        draft = CanonicalDocumentManifestDraft(
            manifest_id=uuid4(),
            context=context,
            acquisition_id=acquisition_id,
            artifact=admission.artifact,
            source_run=ParserRunReference.from_result(run_result),
            quality=quality,
            qualification=qualification.reference(),
            canonical_document=document,
            document_version_id=f"canonical:{content_hash}",
            canonical_content_hash=content_hash,
            canonical_artifact=canonical_descriptor,
            lifecycle=DocumentProcessingLifecycle.CANONICALIZED,
            recorded_at=recorded_at,
        )
        manifest = CanonicalDocumentManifest.from_resolved_record(
            draft, qualification_record=qualification
        )
        self._processing.commit_canonical_manifest(
            context=context,
            manifest=manifest,
            parse_attempt_id=parse_attempt_id,
            qualification_record=qualification.model_dump(mode="json"),
        )
        return manifest

    def load_canonical_document(
        self,
        *,
        context: ArtifactCommandContext,
        document_version_id: str,
    ) -> CanonicalDocument:
        row = self._processing.get_canonical_manifest(
            context=context, document_version_id=document_version_id
        )
        if row is None:
            raise LookupError("canonical version not found")
        descriptor = ArtifactDescriptor.model_validate(row["canonical_artifact"])
        try:
            payload = self._store.read_bytes(descriptor.artifact_id, context=context)
        except ArtifactIntegrityError as error:
            raise CanonicalizationError("canonical_bytes_corrupt") from error
        if hashlib.sha256(payload).hexdigest() != descriptor.digest:
            raise CanonicalizationError("canonical_bytes_corrupt")
        return CanonicalDocument.model_validate_json(payload)
