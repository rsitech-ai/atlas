from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager, suppress
from pathlib import Path
from typing import Protocol
from uuid import UUID

from fastapi import FastAPI, HTTPException, Query, Request
from pydantic import ValidationError
from rsi_atlas_contracts import (
    AcquisitionMethod,
    AcquisitionRequest,
    ArtifactCommandContext,
    DocumentAdmissionRecord,
    SystemStatus,
)
from rsi_atlas_ingestion import MAX_PDF_BYTES, StagedPDFEvidence
from rsi_atlas_ingestion.processing_pipeline import (
    CanonicalPageEvidence,
    ChunkSetEvidence,
    ChunkSetSummary,
    DocumentProcessingStatus,
    RetrievalIndexSummary,
)
from rsi_atlas_storage import AcquisitionConflictError
from starlette.concurrency import run_in_threadpool
from starlette.requests import ClientDisconnect

from rsi_atlas_engine.import_staging import ImportStagingArea, ImportStagingError
from rsi_atlas_engine.ingestion import DocumentIngestionServices
from rsi_atlas_engine.runtime import RuntimeServices


class DocumentAdmissionPort(Protocol):
    def admit_staged(
        self,
        *,
        context: ArtifactCommandContext,
        request: AcquisitionRequest,
        staged_path: Path,
        staged_evidence: StagedPDFEvidence,
    ) -> DocumentAdmissionRecord: ...


class DocumentProcessingPort(Protocol):
    def start(
        self, *, context: ArtifactCommandContext, acquisition_id: UUID
    ) -> DocumentProcessingStatus: ...

    def status(
        self, *, context: ArtifactCommandContext, acquisition_id: UUID
    ) -> DocumentProcessingStatus: ...

    def page(
        self,
        *,
        context: ArtifactCommandContext,
        document_version_id: str,
        page_number: int,
    ) -> CanonicalPageEvidence: ...

    def chunk(
        self,
        *,
        context: ArtifactCommandContext,
        document_version_id: str,
    ) -> tuple[ChunkSetSummary, ...]: ...

    def list_chunk_sets(
        self,
        *,
        context: ArtifactCommandContext,
        document_version_id: str,
    ) -> tuple[ChunkSetSummary, ...]: ...

    def chunk_set(
        self,
        *,
        context: ArtifactCommandContext,
        chunk_set_id: str,
    ) -> ChunkSetEvidence: ...

    def start_indexing(
        self,
        *,
        context: ArtifactCommandContext,
        chunk_set_id: str,
    ) -> RetrievalIndexSummary: ...

    def list_index_versions(
        self,
        *,
        context: ArtifactCommandContext,
        chunk_set_id: str,
    ) -> tuple[RetrievalIndexSummary, ...]: ...

    def activate_publication(
        self,
        *,
        context: ArtifactCommandContext,
        index_version_id: UUID,
    ) -> RetrievalIndexSummary: ...

    def rollback_publication(
        self,
        *,
        context: ArtifactCommandContext,
        index_version_id: UUID,
    ) -> RetrievalIndexSummary: ...


def create_app(
    status_factory: Callable[[], SystemStatus] | None = None,
    *,
    document_admission_service: DocumentAdmissionPort | None = None,
    import_staging_area: ImportStagingArea | None = None,
    document_processing_service: DocumentProcessingPort | None = None,
) -> FastAPI:
    if (document_admission_service is None) != (import_staging_area is None):
        raise ValueError("document admission service and staging area must be configured together")
    factory = status_factory or RuntimeServices.from_environment().status
    configured_ingestion: DocumentIngestionServices | None = None

    def resolve_ingestion() -> tuple[
        DocumentAdmissionPort, ImportStagingArea, DocumentProcessingPort | None
    ]:
        nonlocal configured_ingestion
        if document_admission_service is not None and import_staging_area is not None:
            return document_admission_service, import_staging_area, document_processing_service
        if configured_ingestion is None:
            configured_ingestion = DocumentIngestionServices.from_environment()
        return (
            configured_ingestion.admission_service,
            configured_ingestion.staging_area,
            configured_ingestion.processing_service,
        )

    def resolve_processing() -> DocumentProcessingPort:
        if document_processing_service is not None:
            return document_processing_service
        _, _, processing = resolve_ingestion()
        if processing is None:
            raise RuntimeError("document processing is unavailable")
        return processing

    @asynccontextmanager
    async def lifespan(_application: FastAPI) -> AsyncIterator[None]:
        with suppress(Exception):
            factory()
        yield

    application = FastAPI(
        title="RSI Atlas Engine",
        version="0.1.0",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
        lifespan=lifespan,
    )

    @application.get("/v1/system/status", response_model=SystemStatus)
    def system_status() -> SystemStatus:
        return factory()

    @application.post(
        "/v1/workspaces/{workspace_id}/documents:admit",
        response_model=DocumentAdmissionRecord,
    )
    async def admit_document(
        request: Request,
        workspace_id: UUID,
        filename: str = Query(min_length=1, max_length=255),
        method: str = Query(min_length=1, max_length=32),
        collector_version: str = Query(min_length=1, max_length=64),
    ) -> DocumentAdmissionRecord:
        if _one_header(request, "content-type") != "application/pdf":
            raise HTTPException(status_code=415, detail="Content-Type must be application/pdf.")
        expected_bytes = _content_length(_one_header(request, "content-length"))
        try:
            identities = tuple(
                _required_uuid(_one_header(request, name))
                for name in (
                    "x-rsi-tenant-id",
                    "x-rsi-actor-id",
                    "x-rsi-trace-id",
                    "x-rsi-acquisition-id",
                )
            )
            selected_method = AcquisitionMethod(method)
            if selected_method is AcquisitionMethod.MANUAL_CLI:
                raise ValueError("CLI admission is not an API method")
            context = ArtifactCommandContext(
                tenant_id=identities[0],
                workspace_id=workspace_id,
                actor_id=identities[1],
                trace_id=identities[2],
            )
            admission_request = AcquisitionRequest(
                acquisition_id=identities[3],
                method=selected_method,
                original_filename=filename,
                source_locator=f"manual-import:{identities[3]}",
                declared_media_type="application/pdf",
                collector_version=collector_version,
            )
        except (ValidationError, ValueError) as error:
            raise HTTPException(status_code=422, detail="Admission metadata is invalid.") from error

        try:
            service, staging_area, _processing = await run_in_threadpool(resolve_ingestion)
        except Exception as error:
            raise HTTPException(
                status_code=503,
                detail="Document admission is temporarily unavailable.",
            ) from error

        staged = None
        try:
            staged = await staging_area.stage_chunks(
                request.stream(),
                expected_bytes=expected_bytes,
            )
            return await run_in_threadpool(
                service.admit_staged,
                context=context,
                request=admission_request,
                staged_path=staged.path,
                staged_evidence=staged.evidence,
            )
        except (ImportStagingError, ClientDisconnect) as error:
            raise HTTPException(status_code=400, detail="PDF body length is invalid.") from error
        except AcquisitionConflictError as error:
            raise HTTPException(
                status_code=409,
                detail="Acquisition identity already names different evidence.",
            ) from error
        except (ValidationError, ValueError) as error:
            raise HTTPException(
                status_code=500,
                detail="Document admission produced invalid evidence.",
            ) from error
        except Exception as error:
            raise HTTPException(
                status_code=503,
                detail="Document admission is temporarily unavailable.",
            ) from error
        finally:
            if staged is not None:
                try:
                    staged.cleanup()
                except ImportStagingError as error:
                    raise HTTPException(
                        status_code=500,
                        detail="Document staging cleanup failed safely.",
                    ) from error

    @application.post(
        "/v1/workspaces/{workspace_id}/acquisitions/{acquisition_id}/processing:start",
        response_model=DocumentProcessingStatus,
    )
    async def start_processing(
        request: Request,
        workspace_id: UUID,
        acquisition_id: UUID,
    ) -> DocumentProcessingStatus:
        context = _workspace_context(request, workspace_id)
        try:
            processing = await run_in_threadpool(resolve_processing)
            return await run_in_threadpool(
                processing.start, context=context, acquisition_id=acquisition_id
            )
        except LookupError as error:
            raise HTTPException(status_code=404, detail="Acquisition was not found.") from error
        except Exception as error:
            raise HTTPException(
                status_code=503,
                detail="Document processing is temporarily unavailable.",
            ) from error

    @application.get(
        "/v1/workspaces/{workspace_id}/acquisitions/{acquisition_id}/processing",
        response_model=DocumentProcessingStatus,
    )
    async def processing_status(
        request: Request,
        workspace_id: UUID,
        acquisition_id: UUID,
    ) -> DocumentProcessingStatus:
        context = _workspace_context(request, workspace_id)
        try:
            processing = await run_in_threadpool(resolve_processing)
            return await run_in_threadpool(
                processing.status, context=context, acquisition_id=acquisition_id
            )
        except Exception as error:
            raise HTTPException(
                status_code=503,
                detail="Document processing is temporarily unavailable.",
            ) from error

    @application.get(
        "/v1/workspaces/{workspace_id}/canonical/{document_version_id}/pages/{page_number}",
        response_model=CanonicalPageEvidence,
    )
    async def canonical_page(
        request: Request,
        workspace_id: UUID,
        document_version_id: str,
        page_number: int,
    ) -> CanonicalPageEvidence:
        if page_number < 1 or page_number > 2_000:
            raise HTTPException(status_code=422, detail="Page number is out of bounds.")
        if not document_version_id.startswith("canonical:"):
            raise HTTPException(status_code=422, detail="Canonical version id is invalid.")
        context = _workspace_context(request, workspace_id)
        try:
            processing = await run_in_threadpool(resolve_processing)
            return await run_in_threadpool(
                processing.page,
                context=context,
                document_version_id=document_version_id,
                page_number=page_number,
            )
        except LookupError as error:
            raise HTTPException(status_code=404, detail="Canonical page was not found.") from error
        except Exception as error:
            raise HTTPException(
                status_code=503,
                detail="Canonical page retrieval is temporarily unavailable.",
            ) from error

    @application.post(
        "/v1/workspaces/{workspace_id}/canonical/{document_version_id}/chunking:start",
        response_model=list[ChunkSetSummary],
    )
    async def start_chunking(
        request: Request,
        workspace_id: UUID,
        document_version_id: str,
    ) -> list[ChunkSetSummary]:
        if not document_version_id.startswith("canonical:"):
            raise HTTPException(status_code=422, detail="Canonical version id is invalid.")
        context = _workspace_context(request, workspace_id)
        try:
            processing = await run_in_threadpool(resolve_processing)
            return list(
                await run_in_threadpool(
                    processing.chunk,
                    context=context,
                    document_version_id=document_version_id,
                )
            )
        except LookupError as error:
            raise HTTPException(
                status_code=404, detail="Canonical document was not found."
            ) from error
        except Exception as error:
            raise HTTPException(
                status_code=503,
                detail="Document chunking is temporarily unavailable.",
            ) from error

    @application.get(
        "/v1/workspaces/{workspace_id}/canonical/{document_version_id}/chunk-sets",
        response_model=list[ChunkSetSummary],
    )
    async def list_chunk_sets(
        request: Request,
        workspace_id: UUID,
        document_version_id: str,
    ) -> list[ChunkSetSummary]:
        if not document_version_id.startswith("canonical:"):
            raise HTTPException(status_code=422, detail="Canonical version id is invalid.")
        context = _workspace_context(request, workspace_id)
        try:
            processing = await run_in_threadpool(resolve_processing)
            return list(
                await run_in_threadpool(
                    processing.list_chunk_sets,
                    context=context,
                    document_version_id=document_version_id,
                )
            )
        except Exception as error:
            raise HTTPException(
                status_code=503,
                detail="Chunk set listing is temporarily unavailable.",
            ) from error

    @application.get(
        "/v1/workspaces/{workspace_id}/chunk-sets/{chunk_set_id}",
        response_model=ChunkSetEvidence,
    )
    async def get_chunk_set(
        request: Request,
        workspace_id: UUID,
        chunk_set_id: str,
    ) -> ChunkSetEvidence:
        if not chunk_set_id.startswith("chunkset:"):
            raise HTTPException(status_code=422, detail="Chunk set id is invalid.")
        context = _workspace_context(request, workspace_id)
        try:
            processing = await run_in_threadpool(resolve_processing)
            return await run_in_threadpool(
                processing.chunk_set,
                context=context,
                chunk_set_id=chunk_set_id,
            )
        except LookupError as error:
            raise HTTPException(status_code=404, detail="Chunk set was not found.") from error
        except Exception as error:
            raise HTTPException(
                status_code=503,
                detail="Chunk set retrieval is temporarily unavailable.",
            ) from error

    @application.post(
        "/v1/workspaces/{workspace_id}/chunk-sets/{chunk_set_id}/indexing:start",
        response_model=RetrievalIndexSummary,
    )
    async def start_indexing(
        request: Request,
        workspace_id: UUID,
        chunk_set_id: str,
    ) -> RetrievalIndexSummary:
        if not chunk_set_id.startswith("chunkset:"):
            raise HTTPException(status_code=422, detail="Chunk set id is invalid.")
        context = _workspace_context(request, workspace_id)
        try:
            processing = await run_in_threadpool(resolve_processing)
            return await run_in_threadpool(
                processing.start_indexing,
                context=context,
                chunk_set_id=chunk_set_id,
            )
        except LookupError as error:
            raise HTTPException(status_code=404, detail="Chunk set was not found.") from error
        except Exception as error:
            raise HTTPException(
                status_code=503,
                detail="Index staging is temporarily unavailable.",
            ) from error

    @application.get(
        "/v1/workspaces/{workspace_id}/chunk-sets/{chunk_set_id}/index-versions",
        response_model=list[RetrievalIndexSummary],
    )
    async def list_index_versions(
        request: Request,
        workspace_id: UUID,
        chunk_set_id: str,
    ) -> list[RetrievalIndexSummary]:
        if not chunk_set_id.startswith("chunkset:"):
            raise HTTPException(status_code=422, detail="Chunk set id is invalid.")
        context = _workspace_context(request, workspace_id)
        try:
            processing = await run_in_threadpool(resolve_processing)
            return list(
                await run_in_threadpool(
                    processing.list_index_versions,
                    context=context,
                    chunk_set_id=chunk_set_id,
                )
            )
        except Exception as error:
            raise HTTPException(
                status_code=503,
                detail="Index version listing is temporarily unavailable.",
            ) from error

    @application.post(
        "/v1/workspaces/{workspace_id}/index-versions/{index_version_id}/publication:activate",
        response_model=RetrievalIndexSummary,
    )
    async def activate_publication(
        request: Request,
        workspace_id: UUID,
        index_version_id: UUID,
    ) -> RetrievalIndexSummary:
        context = _workspace_context(request, workspace_id)
        try:
            processing = await run_in_threadpool(resolve_processing)
            return await run_in_threadpool(
                processing.activate_publication,
                context=context,
                index_version_id=index_version_id,
            )
        except LookupError as error:
            raise HTTPException(status_code=404, detail="Index version was not found.") from error
        except Exception as error:
            raise HTTPException(
                status_code=503,
                detail="Publication activation is temporarily unavailable.",
            ) from error

    @application.post(
        "/v1/workspaces/{workspace_id}/index-versions/{index_version_id}/publication:rollback",
        response_model=RetrievalIndexSummary,
    )
    async def rollback_publication(
        request: Request,
        workspace_id: UUID,
        index_version_id: UUID,
    ) -> RetrievalIndexSummary:
        context = _workspace_context(request, workspace_id)
        try:
            processing = await run_in_threadpool(resolve_processing)
            return await run_in_threadpool(
                processing.rollback_publication,
                context=context,
                index_version_id=index_version_id,
            )
        except LookupError as error:
            raise HTTPException(status_code=404, detail="Index version was not found.") from error
        except Exception as error:
            raise HTTPException(
                status_code=503,
                detail="Publication rollback is temporarily unavailable.",
            ) from error

    return application


def _workspace_context(request: Request, workspace_id: UUID) -> ArtifactCommandContext:
    try:
        return ArtifactCommandContext(
            tenant_id=_required_uuid(_one_header(request, "x-rsi-tenant-id")),
            workspace_id=workspace_id,
            actor_id=_required_uuid(_one_header(request, "x-rsi-actor-id")),
            trace_id=_required_uuid(_one_header(request, "x-rsi-trace-id")),
        )
    except (ValidationError, ValueError) as error:
        raise HTTPException(status_code=422, detail="Workspace identity is invalid.") from error


def _content_length(value: str | None) -> int:
    if value is None:
        raise HTTPException(status_code=411, detail="Content-Length is required.")
    if not value.isascii() or not value.isdecimal():
        raise HTTPException(status_code=400, detail="Content-Length is invalid.")
    parsed = int(value)
    if not 1 <= parsed <= MAX_PDF_BYTES:
        raise HTTPException(status_code=413, detail="PDF body exceeds the admission limit.")
    return parsed


def _required_uuid(value: str | None) -> UUID:
    if value is None:
        raise ValueError("required identity is missing")
    return UUID(value)


def _one_header(request: Request, name: str) -> str | None:
    values = request.headers.getlist(name)
    if len(values) > 1:
        raise HTTPException(status_code=422, detail="Admission metadata is invalid.")
    return None if not values else values[0]


app = create_app()
