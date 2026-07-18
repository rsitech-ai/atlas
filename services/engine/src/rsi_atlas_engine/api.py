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


def create_app(
    status_factory: Callable[[], SystemStatus] | None = None,
    *,
    document_admission_service: DocumentAdmissionPort | None = None,
    import_staging_area: ImportStagingArea | None = None,
) -> FastAPI:
    if (document_admission_service is None) != (import_staging_area is None):
        raise ValueError("document admission service and staging area must be configured together")
    factory = status_factory or RuntimeServices.from_environment().status
    configured_ingestion: DocumentIngestionServices | None = None

    def resolve_ingestion() -> tuple[DocumentAdmissionPort, ImportStagingArea]:
        nonlocal configured_ingestion
        if document_admission_service is not None and import_staging_area is not None:
            return document_admission_service, import_staging_area
        if configured_ingestion is None:
            configured_ingestion = DocumentIngestionServices.from_environment()
        return configured_ingestion.admission_service, configured_ingestion.staging_area

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
            service, staging_area = await run_in_threadpool(resolve_ingestion)
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

    return application


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
