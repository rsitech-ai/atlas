"""Acquisition-bound preflight + parse + canonicalize processing composition."""

from __future__ import annotations

import hashlib
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, Protocol
from uuid import UUID

from pydantic import Field
from rsi_atlas_contracts import (
    AdmissionOutcome,
    ArtifactCommandContext,
    CanonicalTextElement,
    DocumentAdmissionRecord,
)
from rsi_atlas_contracts.document_parsing import AdmissionAssessmentDraft
from rsi_atlas_contracts.system_status import StrictModel
from rsi_atlas_storage import ContentAddressedArtifactStore
from rsi_atlas_storage.artifact_repository import ArtifactRepository
from rsi_atlas_storage.document_processing_repository import DocumentProcessingRepository

from rsi_atlas_ingestion.canonical_service import CanonicalizationService
from rsi_atlas_ingestion.canonicalization import CanonicalizationError
from rsi_atlas_ingestion.chunk_service import ChunkService
from rsi_atlas_ingestion.parser_benchmark import QUALIFICATION_PATH, qualify_development_candidate
from rsi_atlas_ingestion.parser_service import ParserService
from rsi_atlas_ingestion.preflight_service import PreflightService
from rsi_atlas_ingestion.worker_runner import DocumentWorkerRunnerError

# Phase 2A quarantine-for-review is the only admitted raw path that may start development parse.
_PROCESSABLE_ADMISSION_OUTCOMES = frozenset(
    {
        AdmissionOutcome.QUARANTINE_FOR_REVIEW,
        AdmissionOutcome.ACCEPT,
        AdmissionOutcome.ACCEPT_WITH_RESTRICTIONS,
    }
)
_BLOCKED_ASSESSMENT_OUTCOMES = frozenset(
    {
        AdmissionOutcome.REQUEST_PASSWORD,
        AdmissionOutcome.REJECT_UNSAFE,
        AdmissionOutcome.REJECT_POLICY_VIOLATION,
        AdmissionOutcome.MARK_EXACT_DUPLICATE,
    }
)


class AdmissionLookup(Protocol):
    def find(
        self, *, context: ArtifactCommandContext, acquisition_id: UUID
    ) -> DocumentAdmissionRecord | None: ...


ProcessingState = Literal[
    "idle",
    "running",
    "canonicalized",
    "review_required",
    "failed",
]


def admission_allows_development_processing(outcome: AdmissionOutcome) -> bool:
    """Return whether Phase 2A admission may offer Process PDF / processing:start."""
    return outcome in _PROCESSABLE_ADMISSION_OUTCOMES


def assessment_allows_development_parse(draft: AdmissionAssessmentDraft) -> bool:
    """Return whether a Phase 2B preflight assessment may continue into parse."""
    if draft.outcome in _BLOCKED_ASSESSMENT_OUTCOMES:
        return False
    if "embedded_files_present" in draft.reason_codes:
        return False
    return draft.outcome in _PROCESSABLE_ADMISSION_OUTCOMES


class DocumentProcessingStatus(StrictModel):
    schema_version: Literal["rsi-atlas.document-processing.status.v1"] = (
        "rsi-atlas.document-processing.status.v1"
    )
    acquisition_id: UUID
    state: ProcessingState
    parse_attempt_id: UUID | None = None
    document_version_id: str | None = Field(default=None, pattern=r"^canonical:[0-9a-f]{64}$")
    canonical_content_hash: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    page_count: int | None = Field(default=None, ge=1, le=2_000)
    warnings: tuple[str, ...] = ()
    failure_code: str | None = None


class CanonicalPageEvidence(StrictModel):
    schema_version: Literal["rsi-atlas.canonical-page.v1"] = "rsi-atlas.canonical-page.v1"
    document_version_id: str = Field(pattern=r"^canonical:[0-9a-f]{64}$")
    page_number: int = Field(ge=1, le=2_000)
    raw_text: str = Field(max_length=2_000_000)
    normalized_text: str = Field(max_length=2_000_000)
    element_count: int = Field(ge=0, le=1_000_000)
    elements: tuple[dict[str, Any], ...] = Field(max_length=256)
    source_artifact_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    canonical_content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    parser_name: str
    parser_version: str


class ChunkSetSummary(StrictModel):
    schema_version: Literal["rsi-atlas.chunk-set-summary.v1"] = "rsi-atlas.chunk-set-summary.v1"
    document_version_id: str = Field(pattern=r"^canonical:[0-9a-f]{64}$")
    chunk_set_id: str = Field(pattern=r"^chunkset:[0-9a-f]{64}$")
    strategy_id: str = Field(pattern=r"^[a-z][a-z0-9_]{0,63}$")
    configuration_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    chunk_set_content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    chunk_count: int = Field(ge=1, le=1_000_000)
    searchable: Literal[False] = False


class ChunkSetEvidence(StrictModel):
    schema_version: Literal["rsi-atlas.chunk-set.v1"] = "rsi-atlas.chunk-set.v1"
    document_version_id: str = Field(pattern=r"^canonical:[0-9a-f]{64}$")
    chunk_set_id: str = Field(pattern=r"^chunkset:[0-9a-f]{64}$")
    strategy_id: str = Field(pattern=r"^[a-z][a-z0-9_]{0,63}$")
    configuration_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    chunk_set_content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    chunk_count: int = Field(ge=1, le=1_000_000)
    searchable: Literal[False] = False
    chunks: tuple[dict[str, Any], ...] = Field(max_length=10_000)


@dataclass(frozen=True, slots=True)
class DocumentProcessingService:
    admissions: AdmissionLookup
    processing: DocumentProcessingRepository
    artifacts: ArtifactRepository
    store: ContentAddressedArtifactStore
    preflight: PreflightService
    parser: ParserService
    canonicalizer: CanonicalizationService
    run_root: Path

    def start(
        self,
        *,
        context: ArtifactCommandContext,
        acquisition_id: UUID,
    ) -> DocumentProcessingStatus:
        admission = self.admissions.find(context=context, acquisition_id=acquisition_id)
        if admission is None:
            raise LookupError("acquisition_not_found")
        if not admission_allows_development_processing(admission.outcome):
            return _blocked_admission_status(
                acquisition_id=acquisition_id, outcome=admission.outcome
            )
        existing = self.status(context=context, acquisition_id=acquisition_id)
        if existing.state == "canonicalized" and existing.document_version_id is not None:
            return existing

        self.run_root.mkdir(parents=True, exist_ok=True)
        staged = self.run_root / f"{acquisition_id}.pdf"
        payload = self.store.read_bytes(admission.artifact.artifact_id, context=context)
        staged.write_bytes(payload)
        try:
            assessment = self.preflight.run(
                context=context,
                acquisition_id=acquisition_id,
                artifact_path=staged,
                run_root=self.run_root / "preflight-runs",
            )
            if not assessment_allows_development_parse(assessment):
                return _blocked_assessment_status(
                    acquisition_id=acquisition_id, assessment=assessment
                )
            if not QUALIFICATION_PATH.is_file():
                qualify_development_candidate()
            benchmark_hash = hashlib.sha256(QUALIFICATION_PATH.read_bytes()).hexdigest()
            parse = self.parser.run(
                context=context,
                acquisition_id=acquisition_id,
                artifact_path=staged,
                run_root=self.run_root / "parse-runs",
            )
            try:
                manifest = self.canonicalizer.canonicalize_and_persist(
                    context=context,
                    acquisition_id=acquisition_id,
                    parse_attempt_id=UUID(parse["attempt_id"]),
                    parse_result=parse["parse_result"],
                    benchmark_hash=benchmark_hash,
                )
            except CanonicalizationError as error:
                return DocumentProcessingStatus(
                    acquisition_id=acquisition_id,
                    state="review_required",
                    parse_attempt_id=UUID(parse["attempt_id"]),
                    warnings=(str(error),),
                    failure_code="quality_review_required",
                )
            return DocumentProcessingStatus(
                acquisition_id=acquisition_id,
                state="canonicalized",
                parse_attempt_id=UUID(parse["attempt_id"]),
                document_version_id=manifest.document_version_id,
                canonical_content_hash=manifest.canonical_content_hash,
                page_count=len(manifest.canonical_document.pages),
                warnings=(),
            )
        except DocumentWorkerRunnerError as error:
            return DocumentProcessingStatus(
                acquisition_id=acquisition_id,
                state="failed",
                warnings=(),
                failure_code=error.code,
            )
        finally:
            staged.unlink(missing_ok=True)

    def status(
        self,
        *,
        context: ArtifactCommandContext,
        acquisition_id: UUID,
    ) -> DocumentProcessingStatus:
        versions = self.processing.list_canonical_versions(
            context=context, acquisition_id=acquisition_id
        )
        if versions:
            latest = versions[-1]
            page_count = len(latest["manifest"]["canonical_document"]["pages"])
            return DocumentProcessingStatus(
                acquisition_id=acquisition_id,
                state="canonicalized",
                document_version_id=latest["document_version_id"],
                canonical_content_hash=latest["canonical_content_hash"],
                page_count=page_count,
                warnings=(),
            )
        return DocumentProcessingStatus(acquisition_id=acquisition_id, state="idle")

    def page(
        self,
        *,
        context: ArtifactCommandContext,
        document_version_id: str,
        page_number: int,
    ) -> CanonicalPageEvidence:
        document = self.canonicalizer.load_canonical_document(
            context=context, document_version_id=document_version_id
        )
        page = next((item for item in document.pages if item.page_number == page_number), None)
        if page is None:
            raise LookupError("page_not_found")
        elements = tuple(
            {
                "kind": element.kind,
                "role": element.role.value if isinstance(element, CanonicalTextElement) else None,
                "reading_order": element.reading_order,
                "raw_text": element.raw_text,
                "normalized_text": element.normalized_text,
                "source_box": element.raw_bounding_box.model_dump(mode="json"),
                "normalized_box": element.bounding_box.model_dump(mode="json"),
                "source_span_id": element.source_span_id,
                "raw_text_hash": element.raw_text_hash,
                "normalized_text_hash": element.normalized_text_hash,
            }
            for element in page.elements[:256]
        )
        raw_text = "\n".join(element.raw_text for element in page.elements)
        normalized_text = "\n".join(element.normalized_text for element in page.elements)
        return CanonicalPageEvidence(
            document_version_id=document_version_id,
            page_number=page_number,
            raw_text=raw_text,
            normalized_text=normalized_text,
            element_count=len(page.elements),
            elements=elements,
            source_artifact_digest=document.source_artifact_digest,
            canonical_content_hash=hashlib.sha256(document.canonical_json_bytes()).hexdigest(),
            parser_name=document.candidate.name,
            parser_version=document.candidate.version,
        )

    def chunk(
        self,
        *,
        context: ArtifactCommandContext,
        document_version_id: str,
    ) -> tuple[ChunkSetSummary, ...]:
        row = self.processing.get_canonical_manifest(
            context=context, document_version_id=document_version_id
        )
        if row is None:
            raise LookupError("canonical_version_not_found")
        acquisition_id = UUID(str(row["acquisition_id"]))
        content_hash = str(row["canonical_content_hash"])
        document = self.canonicalizer.load_canonical_document(
            context=context, document_version_id=document_version_id
        )
        chunker = ChunkService(
            processing=self.processing,
            artifacts=self.artifacts,
            store=self.store,
        )
        chunker.chunk_all_implemented(
            context=context,
            acquisition_id=acquisition_id,
            document_version_id=document_version_id,
            document=document,
            canonical_content_hash=content_hash,
        )
        return self.list_chunk_sets(context=context, document_version_id=document_version_id)

    def list_chunk_sets(
        self,
        *,
        context: ArtifactCommandContext,
        document_version_id: str,
    ) -> tuple[ChunkSetSummary, ...]:
        rows = self.processing.list_chunk_sets(
            context=context, document_version_id=document_version_id
        )
        summaries: list[ChunkSetSummary] = []
        for row in rows:
            manifest = row["manifest"]
            chunk_set = manifest["chunk_set"]
            summaries.append(
                ChunkSetSummary(
                    document_version_id=document_version_id,
                    chunk_set_id=row["chunk_set_id"],
                    strategy_id=row["strategy_id"],
                    configuration_hash=row["configuration_hash"],
                    chunk_set_content_hash=row["chunk_set_content_hash"],
                    chunk_count=int(chunk_set["quality"]["chunk_count"]),
                    searchable=False,
                )
            )
        return tuple(summaries)

    def chunk_set(
        self,
        *,
        context: ArtifactCommandContext,
        chunk_set_id: str,
    ) -> ChunkSetEvidence:
        chunker = ChunkService(
            processing=self.processing,
            artifacts=self.artifacts,
            store=self.store,
        )
        loaded = chunker.load_chunk_set(context=context, chunk_set_id=chunk_set_id)
        chunks = tuple(
            {
                "chunk_id": chunk.chunk_id,
                "ordinal": chunk.ordinal,
                "text": chunk.text,
                "token_count": chunk.token_count,
                "page_numbers": list(chunk.page_numbers),
                "source_element_ids": list(chunk.source_element_ids),
                "metadata": dict(chunk.metadata),
            }
            for chunk in loaded.chunks[:10_000]
        )
        return ChunkSetEvidence(
            document_version_id=loaded.document_version_id,
            chunk_set_id=loaded.chunk_set_id,
            strategy_id=loaded.strategy.strategy_id,
            configuration_hash=loaded.strategy.configuration_hash,
            chunk_set_content_hash=loaded.content_hash(),
            chunk_count=loaded.quality.chunk_count,
            searchable=False,
            chunks=chunks,
        )


def _blocked_admission_status(
    *, acquisition_id: UUID, outcome: AdmissionOutcome
) -> DocumentProcessingStatus:
    if outcome is AdmissionOutcome.REQUEST_PASSWORD:
        state: ProcessingState = "review_required"
        code = "admission_password_required"
    else:
        state = "failed"
        code = "admission_not_processable"
    return DocumentProcessingStatus(
        acquisition_id=acquisition_id,
        state=state,
        warnings=(f"admission_outcome:{outcome.value}",),
        failure_code=code,
    )


def _blocked_assessment_status(
    *, acquisition_id: UUID, assessment: AdmissionAssessmentDraft
) -> DocumentProcessingStatus:
    if assessment.outcome is AdmissionOutcome.REQUEST_PASSWORD:
        state: ProcessingState = "review_required"
        code = "preflight_password_required"
    elif assessment.outcome in {
        AdmissionOutcome.REJECT_UNSAFE,
        AdmissionOutcome.REJECT_POLICY_VIOLATION,
    }:
        state = "failed"
        code = "preflight_rejected"
    else:
        state = "review_required"
        code = "preflight_review_required"
    return DocumentProcessingStatus(
        acquisition_id=acquisition_id,
        state=state,
        warnings=tuple(assessment.reason_codes),
        failure_code=code,
    )


def clear_directory(path: Path) -> None:
    if path.exists():
        shutil.rmtree(path)
    path.mkdir(parents=True, exist_ok=True)
