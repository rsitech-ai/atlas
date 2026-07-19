import os
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager, suppress
from datetime import datetime
from json import dumps
from pathlib import Path
from typing import Any, Protocol
from uuid import UUID

from fastapi import FastAPI, HTTPException, Query, Request
from pydantic import ValidationError
from rsi_atlas_contracts import (
    AcquisitionMethod,
    AcquisitionRequest,
    AlertLifecycle,
    ArtifactCommandContext,
    ComparisonAxis,
    DocumentAdmissionRecord,
    EvidencePacket,
    MonitoringRule,
    Observation,
    ProviderQualityState,
    ReportDraft,
    ResearchQuery,
    RetrievalAbstention,
    RetrievalPlan,
    ReviewAction,
    ReviewDecision,
    SemanticTriageRequest,
    SpecialistFinding,
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
from rsi_atlas_research.workflow import workflow_id_for_query
from rsi_atlas_storage import (
    AcquisitionConflictError,
    DatabaseSettings,
    MigrationRunner,
    PostgresDatabase,
)
from starlette.concurrency import run_in_threadpool
from starlette.requests import ClientDisconnect

from rsi_atlas_engine.collectors import CollectorPort, CollectorServices
from rsi_atlas_engine.import_staging import ImportStagingArea, ImportStagingError
from rsi_atlas_engine.ingestion import DocumentIngestionServices
from rsi_atlas_engine.ipc_auth import IpcAuthMiddleware
from rsi_atlas_engine.monitoring import (
    AlertTransitionError,
    InMemoryMonitoringService,
    MonitoringPort,
    SemanticTriageBlocked,
)
from rsi_atlas_engine.phase6 import Phase6Service
from rsi_atlas_engine.research import ResearchFacade, ResearchServices
from rsi_atlas_engine.runtime import RuntimePaths, RuntimeServices

_DATABASE_CONNECT_TIMEOUT_SECONDS = 1
_DATABASE_STATEMENT_TIMEOUT_MS = 10_000
_DATABASE_LOCK_TIMEOUT_MS = 5_000
_DATABASE_TRANSACTION_TIMEOUT_MS = 15_000


def _database_from_environment() -> PostgresDatabase:
    paths = RuntimePaths.from_environment()
    socket_directory = paths.data_root / "postgres" / "socket"
    conninfo = f"host='{socket_directory}' port=5432 user='atlas' dbname='atlas'"
    settings = DatabaseSettings.from_conninfo(
        conninfo,
        connect_timeout_seconds=_DATABASE_CONNECT_TIMEOUT_SECONDS,
        statement_timeout_ms=_DATABASE_STATEMENT_TIMEOUT_MS,
        lock_timeout_ms=_DATABASE_LOCK_TIMEOUT_MS,
        transaction_timeout_ms=_DATABASE_TRANSACTION_TIMEOUT_MS,
    )
    database = PostgresDatabase(settings)
    MigrationRunner(database, paths.migration_root).apply_all()
    return database


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


class ResearchPort(Protocol):
    def retrieve(self, *, query: ResearchQuery) -> EvidencePacket | RetrievalAbstention: ...

    def run_document_specialist(
        self,
        *,
        query: ResearchQuery,
        packet: EvidencePacket,
        subquestion: str | None = None,
    ) -> SpecialistFinding: ...

    def draft_report(
        self,
        *,
        query: ResearchQuery,
        packet: EvidencePacket,
        finding: SpecialistFinding,
        title: str,
    ) -> ReportDraft: ...

    def review_report(
        self,
        *,
        query: ResearchQuery,
        report: ReportDraft,
        action: ReviewAction,
        rationale: str,
    ) -> ReviewDecision: ...

    def start_workflow(self, *, query: ResearchQuery, title: str) -> dict[str, object]: ...

    def resume_workflow(
        self,
        *,
        query: ResearchQuery,
        title: str,
        human_decision: ReviewDecision | None = None,
    ) -> dict[str, object]: ...

    def get_workflow(self, *, context: ArtifactCommandContext, workflow_id: UUID) -> Any | None: ...

    def list_workflows(self, *, context: ArtifactCommandContext, limit: int = 50) -> list[Any]: ...


def create_app(
    status_factory: Callable[[], SystemStatus] | None = None,
    *,
    document_admission_service: DocumentAdmissionPort | None = None,
    import_staging_area: ImportStagingArea | None = None,
    document_processing_service: DocumentProcessingPort | None = None,
    research_service: ResearchPort | None = None,
    collector_service: CollectorPort | None = None,
    monitoring_service: MonitoringPort | None = None,
    phase6_service: Phase6Service | None = None,
    require_ipc_auth: bool | None = None,
    ipc_token_path: Path | None = None,
) -> FastAPI:
    if (document_admission_service is None) != (import_staging_area is None):
        raise ValueError("document admission service and staging area must be configured together")
    factory = status_factory or RuntimeServices.from_environment().status
    configured_ingestion: DocumentIngestionServices | None = None
    configured_research: ResearchFacade | None = None
    configured_collectors: CollectorServices | None = None
    configured_monitoring: InMemoryMonitoringService | None = None
    shared_database: PostgresDatabase | None = None

    def resolve_database() -> PostgresDatabase:
        nonlocal shared_database
        if shared_database is None:
            shared_database = _database_from_environment()
        return shared_database

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

    def resolve_research() -> ResearchPort:
        nonlocal configured_research
        if research_service is not None:
            return research_service
        if configured_research is None:
            configured_research = ResearchFacade(ResearchServices.from_environment())
        return configured_research

    def resolve_collectors() -> CollectorPort:
        nonlocal configured_collectors
        if collector_service is not None:
            return collector_service
        if configured_collectors is None:
            configured_collectors = CollectorServices.from_database(resolve_database())
        return configured_collectors

    def resolve_monitoring() -> MonitoringPort:
        nonlocal configured_monitoring
        if monitoring_service is not None:
            return monitoring_service
        if configured_monitoring is None:
            configured_monitoring = InMemoryMonitoringService.from_database(resolve_database())
        return configured_monitoring

    def resolve_phase6() -> Phase6Service:
        return phase6_service or Phase6Service()

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

    auth_enabled = (
        require_ipc_auth
        if require_ipc_auth is not None
        else os.environ.get("RSI_ATLAS_IPC_AUTH", "").strip().lower() in {"1", "true", "yes", "on"}
    )
    if auth_enabled:
        token_path = ipc_token_path or (
            RuntimePaths.from_environment().data_root / "ipc" / "engine.token"
        )
        application.add_middleware(IpcAuthMiddleware, token_path=token_path, enabled=True)

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

    @application.post("/v1/workspaces/{workspace_id}/research:retrieve")
    async def research_retrieve(
        request: Request,
        workspace_id: UUID,
    ) -> dict[str, object]:
        context = _workspace_context(request, workspace_id)
        try:
            query = ResearchQuery.model_validate_json(await request.body())
            if query.context.workspace_id != context.workspace_id:
                raise HTTPException(status_code=422, detail="Workspace identity is invalid.")
            research = await run_in_threadpool(resolve_research)
            result = await run_in_threadpool(research.retrieve, query=query)
            return result.model_dump(mode="json")
        except HTTPException:
            raise
        except ValidationError as error:
            raise HTTPException(status_code=422, detail="Research query is invalid.") from error
        except Exception as error:
            raise HTTPException(
                status_code=503,
                detail="Research retrieval is temporarily unavailable.",
            ) from error

    @application.post(
        "/v1/workspaces/{workspace_id}/research/specialist:document",
    )
    async def research_document_specialist(
        request: Request,
        workspace_id: UUID,
    ) -> dict[str, object]:
        context = _workspace_context(request, workspace_id)
        try:
            body = await request.json()
            query = ResearchQuery.model_validate_json(dumps(body["query"]))
            packet = EvidencePacket.model_validate_json(dumps(body["packet"]))
            if query.context.workspace_id != context.workspace_id:
                raise HTTPException(status_code=422, detail="Workspace identity is invalid.")
            subquestion = body.get("subquestion")
            research = await run_in_threadpool(resolve_research)
            finding = await run_in_threadpool(
                research.run_document_specialist,
                query=query,
                packet=packet,
                subquestion=str(subquestion) if subquestion is not None else None,
            )
            return finding.model_dump(mode="json")
        except HTTPException:
            raise
        except (ValidationError, KeyError, TypeError, ValueError) as error:
            raise HTTPException(status_code=422, detail="Specialist request is invalid.") from error
        except Exception as error:
            raise HTTPException(
                status_code=503,
                detail="Document specialist is temporarily unavailable.",
            ) from error

    @application.post(
        "/v1/workspaces/{workspace_id}/research/reports:draft",
    )
    async def research_draft_report(
        request: Request,
        workspace_id: UUID,
    ) -> dict[str, object]:
        context = _workspace_context(request, workspace_id)
        try:
            body = await request.json()
            query = ResearchQuery.model_validate_json(dumps(body["query"]))
            packet = EvidencePacket.model_validate_json(dumps(body["packet"]))
            finding = SpecialistFinding.model_validate_json(dumps(body["finding"]))
            title = str(body["title"])
            if query.context.workspace_id != context.workspace_id:
                raise HTTPException(status_code=422, detail="Workspace identity is invalid.")
            research = await run_in_threadpool(resolve_research)
            draft = await run_in_threadpool(
                research.draft_report,
                query=query,
                packet=packet,
                finding=finding,
                title=title,
            )
            return draft.model_dump(mode="json")
        except HTTPException:
            raise
        except (ValidationError, KeyError, TypeError, ValueError) as error:
            raise HTTPException(
                status_code=422, detail="Report draft request is invalid."
            ) from error
        except Exception as error:
            raise HTTPException(
                status_code=503,
                detail="Report drafting is temporarily unavailable.",
            ) from error

    @application.post(
        "/v1/workspaces/{workspace_id}/research/reports/{report_id}/review",
    )
    async def research_review_report(
        request: Request,
        workspace_id: UUID,
        report_id: str,
    ) -> dict[str, object]:
        context = _workspace_context(request, workspace_id)
        try:
            body = await request.json()
            query = ResearchQuery.model_validate_json(dumps(body["query"]))
            report = ReportDraft.model_validate_json(dumps(body["report"]))
            action = ReviewAction(str(body["action"]))
            rationale = str(body["rationale"])
            if report.report_id != report_id:
                raise HTTPException(status_code=422, detail="Report identity is invalid.")
            if query.context.workspace_id != context.workspace_id:
                raise HTTPException(status_code=422, detail="Workspace identity is invalid.")
            research = await run_in_threadpool(resolve_research)
            decision = await run_in_threadpool(
                research.review_report,
                query=query,
                report=report,
                action=action,
                rationale=rationale,
            )
            return decision.model_dump(mode="json")
        except HTTPException:
            raise
        except (ValidationError, KeyError, TypeError, ValueError) as error:
            raise HTTPException(status_code=422, detail="Review request is invalid.") from error
        except Exception as error:
            raise HTTPException(
                status_code=503,
                detail="Report review is temporarily unavailable.",
            ) from error

    @application.post("/v1/workspaces/{workspace_id}/research/workflows:start")
    async def research_workflow_start(
        request: Request,
        workspace_id: UUID,
    ) -> dict[str, object]:
        context = _workspace_context(request, workspace_id)
        try:
            body = await request.json()
            query = ResearchQuery.model_validate_json(dumps(body["query"]))
            title = str(body.get("title") or "Research draft")
            if query.context.workspace_id != context.workspace_id:
                raise HTTPException(status_code=422, detail="Workspace identity is invalid.")
            research = await run_in_threadpool(resolve_research)
            return await run_in_threadpool(research.start_workflow, query=query, title=title)
        except HTTPException:
            raise
        except (ValidationError, KeyError, TypeError, ValueError) as error:
            raise HTTPException(status_code=422, detail="Workflow start is invalid.") from error
        except Exception as error:
            raise HTTPException(
                status_code=503,
                detail="Research workflow is temporarily unavailable.",
            ) from error

    @application.post(
        "/v1/workspaces/{workspace_id}/research/workflows/{workflow_id}:resume",
    )
    async def research_workflow_resume(
        request: Request,
        workspace_id: UUID,
        workflow_id: UUID,
    ) -> dict[str, object]:
        context = _workspace_context(request, workspace_id)
        try:
            body = await request.json()
            query = ResearchQuery.model_validate_json(dumps(body["query"]))
            title = str(body.get("title") or "Research draft")
            human_decision = None
            if "human_decision" in body and body["human_decision"] is not None:
                human_decision = ReviewDecision.model_validate_json(dumps(body["human_decision"]))
            if query.context.workspace_id != context.workspace_id:
                raise HTTPException(status_code=422, detail="Workspace identity is invalid.")
            if workflow_id_for_query(query_id=query.query_id) != workflow_id:
                raise HTTPException(status_code=422, detail="Workflow identity is invalid.")
            research = await run_in_threadpool(resolve_research)
            return await run_in_threadpool(
                research.resume_workflow,
                query=query,
                title=title,
                human_decision=human_decision,
            )
        except HTTPException:
            raise
        except (ValidationError, KeyError, TypeError, ValueError) as error:
            raise HTTPException(status_code=422, detail="Workflow resume is invalid.") from error
        except Exception as error:
            raise HTTPException(
                status_code=503,
                detail="Research workflow is temporarily unavailable.",
            ) from error

    @application.get("/v1/workspaces/{workspace_id}/research/workflows")
    async def research_workflow_list(
        request: Request,
        workspace_id: UUID,
        limit: int = Query(default=50, ge=1, le=200),
    ) -> dict[str, object]:
        context = _workspace_context(request, workspace_id)
        try:
            research = await run_in_threadpool(resolve_research)
            attempts = await run_in_threadpool(
                research.list_workflows, context=context, limit=limit
            )
            return {
                "workflows": [
                    item.model_dump(mode="json") if hasattr(item, "model_dump") else item
                    for item in attempts
                ]
            }
        except Exception as error:
            raise HTTPException(
                status_code=503,
                detail="Research workflow listing is temporarily unavailable.",
            ) from error

    @application.get("/v1/workspaces/{workspace_id}/research/workflows/{workflow_id}")
    async def research_workflow_get(
        request: Request,
        workspace_id: UUID,
        workflow_id: UUID,
    ) -> dict[str, object]:
        context = _workspace_context(request, workspace_id)
        try:
            research = await run_in_threadpool(resolve_research)
            attempt = await run_in_threadpool(
                research.get_workflow, context=context, workflow_id=workflow_id
            )
            if attempt is None:
                raise HTTPException(status_code=404, detail="Workflow was not found.")
            payload = attempt.model_dump(mode="json") if hasattr(attempt, "model_dump") else attempt
            return {"workflow": payload}
        except HTTPException:
            raise
        except Exception as error:
            raise HTTPException(
                status_code=503,
                detail="Research workflow retrieval is temporarily unavailable.",
            ) from error

    @application.post("/v1/workspaces/{workspace_id}/collectors:import-fixture")
    async def collectors_import_fixture(
        request: Request,
        workspace_id: UUID,
    ) -> dict[str, object]:
        context = _workspace_context(request, workspace_id)
        try:
            body = await request.json()
            fixture_name = str(body["fixture_name"])
            quality_raw = body.get("provider_quality", ProviderQualityState.SINGLE_SOURCE.value)
            provider_quality = ProviderQualityState(str(quality_raw))
            collectors = await run_in_threadpool(resolve_collectors)
            result = await run_in_threadpool(
                collectors.import_fixture,
                context=context,
                fixture_name=fixture_name,
                provider_quality=provider_quality,
            )
            return {
                "envelope": result.envelope.model_dump(mode="json"),
                "observation": (
                    None
                    if result.observation is None
                    else result.observation.model_dump(mode="json")
                ),
                "quarantine": (
                    None if result.quarantine is None else result.quarantine.model_dump(mode="json")
                ),
            }
        except HTTPException:
            raise
        except (ValidationError, KeyError, TypeError, ValueError) as error:
            raise HTTPException(status_code=422, detail="Fixture import is invalid.") from error
        except Exception as error:
            raise HTTPException(
                status_code=503,
                detail="Collector import is temporarily unavailable.",
            ) from error

    @application.get("/v1/workspaces/{workspace_id}/observations")
    async def list_observations(
        request: Request,
        workspace_id: UUID,
        as_of: str = Query(min_length=1, max_length=64),
        subject_id: str | None = Query(default=None, max_length=128),
    ) -> dict[str, object]:
        context = _workspace_context(request, workspace_id)
        try:
            stamped = datetime.fromisoformat(as_of.replace("Z", "+00:00"))
            collectors = await run_in_threadpool(resolve_collectors)
            observations = await run_in_threadpool(
                collectors.list_observations,
                context=context,
                as_of=stamped,
                subject_id=subject_id,
            )
            return {
                "observations": [item.model_dump(mode="json") for item in observations],
            }
        except HTTPException:
            raise
        except (ValidationError, TypeError, ValueError) as error:
            raise HTTPException(status_code=422, detail="Observation query is invalid.") from error
        except Exception as error:
            raise HTTPException(
                status_code=503,
                detail="Observation listing is temporarily unavailable.",
            ) from error

    @application.post("/v1/workspaces/{workspace_id}/monitoring:evaluate")
    async def monitoring_evaluate(
        request: Request,
        workspace_id: UUID,
    ) -> dict[str, object]:
        context = _workspace_context(request, workspace_id)
        try:
            monitoring = await run_in_threadpool(resolve_monitoring)
            body = await request.json()
            previous_raw = body.get("previous_observation")
            previous = (
                None
                if previous_raw is None
                else Observation.model_validate_json(dumps(previous_raw))
            )
            current = Observation.model_validate_json(dumps(body["current_observation"]))
            rules = tuple(
                MonitoringRule.model_validate_json(dumps(item)) for item in body.get("rules", [])
            )
            affected = tuple(str(item) for item in body.get("affected_report_ids", []))
            result = await run_in_threadpool(
                monitoring.evaluate_change,
                context=context,
                previous=previous,
                current=current,
                rules=rules,
                affected_report_ids=affected,
            )
            detection = result["detection"]
            matched_rules = result["matched_rules"]
            decisions = result["decisions"]
            alerts = result["alerts"]
            created = result["created"]
            return {
                "detection": detection.model_dump(mode="json"),  # type: ignore[attr-defined]
                "matched_rules": [
                    rule.model_dump(mode="json")
                    for rule in matched_rules  # type: ignore[attr-defined]
                ],
                "decisions": [
                    decision.model_dump(mode="json")
                    for decision in decisions  # type: ignore[attr-defined]
                ],
                "alerts": [alert.model_dump(mode="json") for alert in alerts],  # type: ignore[attr-defined]
                "created": list(created),  # type: ignore[call-overload]
            }
        except HTTPException:
            raise
        except RuntimeError as error:
            raise HTTPException(
                status_code=503,
                detail="Monitoring evaluate is temporarily unavailable.",
            ) from error
        except (ValidationError, KeyError, TypeError, ValueError) as error:
            raise HTTPException(
                status_code=422,
                detail="Monitoring evaluate is invalid.",
            ) from error
        except Exception as error:
            raise HTTPException(
                status_code=503,
                detail="Monitoring evaluate is temporarily unavailable.",
            ) from error

    @application.post("/v1/workspaces/{workspace_id}/monitoring/alerts/{alert_id}:transition")
    async def monitoring_transition(
        request: Request,
        workspace_id: UUID,
        alert_id: str,
    ) -> dict[str, object]:
        context = _workspace_context(request, workspace_id)
        try:
            monitoring = await run_in_threadpool(resolve_monitoring)
            body = await request.json()
            to_status = AlertLifecycle(str(body["to_status"]))
            note = str(body.get("note", ""))
            result = await run_in_threadpool(
                monitoring.transition,
                context=context,
                alert_id=alert_id,
                to_status=to_status,
                note=note,
            )
            return {
                "alert": result["alert"].model_dump(mode="json"),  # type: ignore[attr-defined]
                "event": result["event"].model_dump(mode="json"),  # type: ignore[attr-defined]
            }
        except HTTPException:
            raise
        except RuntimeError as error:
            raise HTTPException(
                status_code=503,
                detail="Alert transition is temporarily unavailable.",
            ) from error
        except LookupError as error:
            raise HTTPException(status_code=404, detail="Alert was not found.") from error
        except AlertTransitionError as error:
            raise HTTPException(status_code=422, detail="Alert transition is illegal.") from error
        except (ValidationError, KeyError, TypeError, ValueError) as error:
            raise HTTPException(status_code=422, detail="Alert transition is invalid.") from error
        except Exception as error:
            raise HTTPException(
                status_code=503,
                detail="Alert transition is temporarily unavailable.",
            ) from error

    @application.post("/v1/workspaces/{workspace_id}/monitoring:invalidate")
    async def monitoring_invalidate(
        request: Request,
        workspace_id: UUID,
    ) -> dict[str, object]:
        context = _workspace_context(request, workspace_id)
        try:
            monitoring = await run_in_threadpool(resolve_monitoring)
            body = await request.json()
            previous_raw = body.get("previous_observation")
            previous = (
                None
                if previous_raw is None
                else Observation.model_validate_json(dumps(previous_raw))
            )
            current = Observation.model_validate_json(dumps(body["current_observation"]))
            affected = tuple(str(item) for item in body.get("affected_report_ids", []))
            alert_id = body.get("alert_id")
            record = await run_in_threadpool(
                monitoring.invalidate,
                context=context,
                previous=previous,
                current=current,
                affected_report_ids=affected,
                alert_id=None if alert_id is None else str(alert_id),
            )
            return {"invalidation": record.model_dump(mode="json")}
        except HTTPException:
            raise
        except RuntimeError as error:
            raise HTTPException(
                status_code=503,
                detail="Research invalidation is temporarily unavailable.",
            ) from error
        except (ValidationError, KeyError, TypeError, ValueError) as error:
            raise HTTPException(
                status_code=422,
                detail="Invalidation request is invalid.",
            ) from error
        except Exception as error:
            raise HTTPException(
                status_code=503,
                detail="Research invalidation is temporarily unavailable.",
            ) from error

    @application.post("/v1/workspaces/{workspace_id}/monitoring:launch-research")
    async def monitoring_launch(
        request: Request,
        workspace_id: UUID,
    ) -> dict[str, object]:
        context = _workspace_context(request, workspace_id)
        try:
            monitoring = await run_in_threadpool(resolve_monitoring)
            body = await request.json()
            alert_id = str(body["alert_id"])
            plan = RetrievalPlan.model_validate_json(dumps(body["plan"]))
            launch = await run_in_threadpool(
                monitoring.launch,
                context=context,
                alert_id=alert_id,
                plan=plan,
            )
            return {"launch": launch.model_dump(mode="json")}
        except HTTPException:
            raise
        except RuntimeError as error:
            raise HTTPException(
                status_code=503,
                detail="Research launch is temporarily unavailable.",
            ) from error
        except LookupError as error:
            raise HTTPException(status_code=404, detail="Alert was not found.") from error
        except (ValidationError, KeyError, TypeError, ValueError) as error:
            raise HTTPException(status_code=422, detail="Research launch is invalid.") from error
        except Exception as error:
            raise HTTPException(
                status_code=503,
                detail="Research launch is temporarily unavailable.",
            ) from error

    @application.post("/v1/workspaces/{workspace_id}/monitoring:comparison")
    async def monitoring_comparison(
        request: Request,
        workspace_id: UUID,
    ) -> dict[str, object]:
        context = _workspace_context(request, workspace_id)
        try:
            monitoring = await run_in_threadpool(resolve_monitoring)
            body = await request.json()
            observations = tuple(
                Observation.model_validate_json(dumps(item)) for item in body["observations"]
            )
            axes = tuple(ComparisonAxis(str(item)) for item in body["axes"])
            as_of = datetime.fromisoformat(str(body["as_of"]).replace("Z", "+00:00"))
            matrix = await run_in_threadpool(
                monitoring.comparison,
                context=context,
                observations=observations,
                axes=axes,
                as_of=as_of,
            )
            return {"matrix": matrix.model_dump(mode="json")}
        except HTTPException:
            raise
        except RuntimeError as error:
            raise HTTPException(
                status_code=503,
                detail="Comparison matrix is temporarily unavailable.",
            ) from error
        except (ValidationError, KeyError, TypeError, ValueError) as error:
            raise HTTPException(status_code=422, detail="Comparison request is invalid.") from error
        except Exception as error:
            raise HTTPException(
                status_code=503,
                detail="Comparison matrix is temporarily unavailable.",
            ) from error

    @application.post("/v1/workspaces/{workspace_id}/monitoring:timeline")
    async def monitoring_timeline(
        request: Request,
        workspace_id: UUID,
    ) -> dict[str, object]:
        context = _workspace_context(request, workspace_id)
        try:
            monitoring = await run_in_threadpool(resolve_monitoring)
            body = await request.json()
            observations = tuple(
                Observation.model_validate_json(dumps(item)) for item in body["observations"]
            )
            as_of = datetime.fromisoformat(str(body["as_of"]).replace("Z", "+00:00"))
            timeline = await run_in_threadpool(
                monitoring.timeline,
                context=context,
                observations=observations,
                as_of=as_of,
            )
            return {"timeline": timeline.model_dump(mode="json")}
        except HTTPException:
            raise
        except RuntimeError as error:
            raise HTTPException(
                status_code=503,
                detail="Timeline is temporarily unavailable.",
            ) from error
        except (ValidationError, KeyError, TypeError, ValueError) as error:
            raise HTTPException(status_code=422, detail="Timeline request is invalid.") from error
        except Exception as error:
            raise HTTPException(
                status_code=503,
                detail="Timeline is temporarily unavailable.",
            ) from error

    @application.post("/v1/workspaces/{workspace_id}/monitoring:semantic-triage")
    async def monitoring_semantic_triage(
        request: Request,
        workspace_id: UUID,
    ) -> dict[str, object]:
        _workspace_context(request, workspace_id)
        try:
            monitoring = await run_in_threadpool(resolve_monitoring)
            body = await request.json()
            triage_request = SemanticTriageRequest.model_validate_json(dumps(body))
            await run_in_threadpool(monitoring.triage, request=triage_request)
            raise HTTPException(status_code=503, detail="Semantic triage is unavailable.")
        except SemanticTriageBlocked as error:
            raise HTTPException(
                status_code=422,
                detail="blocked_semantic_triage",
            ) from error
        except HTTPException:
            raise
        except RuntimeError as error:
            raise HTTPException(
                status_code=503,
                detail="Semantic triage is temporarily unavailable.",
            ) from error
        except (ValidationError, KeyError, TypeError, ValueError) as error:
            raise HTTPException(status_code=422, detail="Semantic triage is invalid.") from error
        except Exception as error:
            raise HTTPException(
                status_code=503,
                detail="Semantic triage is temporarily unavailable.",
            ) from error

    @application.post("/v1/evaluation:run")
    async def evaluation_run(request: Request) -> dict[str, object]:
        try:
            service = await run_in_threadpool(resolve_phase6)
            body = await request.json()
            return await run_in_threadpool(
                service.run_evaluation,
                include_judge=bool(body.get("include_judge", False)),
                actuals=body.get("actuals"),
            )
        except (ValidationError, KeyError, TypeError, ValueError) as error:
            raise HTTPException(status_code=422, detail="Evaluation request is invalid.") from error
        except Exception as error:
            raise HTTPException(status_code=503, detail="Evaluation is unavailable.") from error

    @application.post("/v1/engineering/codex:gate")
    async def codex_gate(request: Request) -> dict[str, object]:
        try:
            service = await run_in_threadpool(resolve_phase6)
            body = await request.json()
            return await run_in_threadpool(
                service.codex_gate,
                failure_summary=str(body.get("failure_summary", "loopback failure")),
                raw_inputs=body.get("raw_inputs") or {},
                expected_behavior=str(body.get("expected_behavior", "pass")),
                actual_behavior=str(body.get("actual_behavior", "fail")),
                diff_text=str(body.get("diff_text", "")),
            )
        except (ValidationError, KeyError, TypeError, ValueError) as error:
            raise HTTPException(status_code=422, detail="Codex gate request is invalid.") from error
        except Exception as error:
            raise HTTPException(status_code=503, detail="Codex gate is unavailable.") from error

    @application.post("/v1/recovery/backup:create")
    async def backup_create(request: Request) -> dict[str, object]:
        try:
            service = await run_in_threadpool(resolve_phase6)
            body = await request.json()
            return await run_in_threadpool(
                service.create_backup,
                source_root=Path(str(body["source_root"])),
                destination_root=Path(str(body["destination_root"])),
            )
        except (ValidationError, KeyError, TypeError, ValueError, FileNotFoundError) as error:
            raise HTTPException(status_code=422, detail="Backup request is invalid.") from error
        except Exception as error:
            raise HTTPException(status_code=503, detail="Backup is unavailable.") from error

    @application.post("/v1/recovery/backup:restore-verify")
    async def backup_restore_verify(request: Request) -> dict[str, object]:
        try:
            service = await run_in_threadpool(resolve_phase6)
            body = await request.json()
            destination = body.get("destination")
            return await run_in_threadpool(
                service.restore_verify,
                backup_root=Path(str(body["backup_root"])),
                destination=Path(str(destination)) if destination else None,
            )
        except (ValidationError, KeyError, TypeError, ValueError) as error:
            raise HTTPException(status_code=422, detail="Restore verify is invalid.") from error
        except Exception as error:
            raise HTTPException(status_code=503, detail="Restore verify is unavailable.") from error

    @application.post("/v1/recovery/safe-mode:enter")
    async def safe_mode_enter(request: Request) -> dict[str, object]:
        try:
            service = await run_in_threadpool(resolve_phase6)
            body = await request.json()
            state = await run_in_threadpool(
                service.enter_safe_mode,
                reason=str(body.get("reason", "operator")),
            )
            return state.model_dump(mode="json")
        except (ValidationError, KeyError, TypeError, ValueError) as error:
            raise HTTPException(status_code=422, detail="Safe Mode request is invalid.") from error
        except Exception as error:
            raise HTTPException(status_code=503, detail="Safe Mode is unavailable.") from error

    @application.get("/v1/recovery/safe-mode")
    async def safe_mode_get() -> dict[str, object]:
        service = await run_in_threadpool(resolve_phase6)
        return (await run_in_threadpool(service.safe_mode_state)).model_dump(mode="json")

    @application.post("/v1/release:check")
    async def release_check(request: Request) -> dict[str, object]:
        try:
            service = await run_in_threadpool(resolve_phase6)
            body = await request.json()
            report = await run_in_threadpool(
                service.release_check,
                require_release=bool(body.get("require_release", False)),
            )
            return report.model_dump(mode="json")
        except (ValidationError, KeyError, TypeError, ValueError) as error:
            raise HTTPException(status_code=422, detail="Release check is invalid.") from error
        except Exception as error:
            raise HTTPException(status_code=503, detail="Release check is unavailable.") from error

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
