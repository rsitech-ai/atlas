import os
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal
from uuid import UUID

from rsi_atlas_contracts import ArtifactCommandContext, SafeModeCapability
from rsi_atlas_contracts.runtime_resources import RuntimeResources
from rsi_atlas_ingestion import DocumentAdmissionService
from rsi_atlas_ingestion.canonical_service import CanonicalizationService
from rsi_atlas_ingestion.parser_service import ParserService
from rsi_atlas_ingestion.preflight_service import PreflightService
from rsi_atlas_ingestion.processing_pipeline import DocumentProcessingService
from rsi_atlas_ingestion.worker_runner import DocumentWorkerRunner
from rsi_atlas_recovery import SafeModeController
from rsi_atlas_storage import (
    AcquisitionRepository,
    ArtifactRepository,
    ContentAddressedArtifactStore,
    DatabaseSettings,
    DocumentProcessingRepository,
    MigrationRunner,
    PostgresDatabase,
)

from rsi_atlas_engine.import_staging import ImportStagingArea
from rsi_atlas_engine.runtime import RuntimePaths
from rsi_atlas_engine.safe_mode import apply_or_verify_migrations, runtime_safe_mode

_DATABASE_CONNECT_TIMEOUT_SECONDS = 1
_DATABASE_STATEMENT_TIMEOUT_MS = 10_000
_DATABASE_LOCK_TIMEOUT_MS = 5_000
_DATABASE_TRANSACTION_TIMEOUT_MS = 15_000


@dataclass(frozen=True, slots=True)
class SafeModeProcessingService:
    service: DocumentProcessingService
    safe_mode: SafeModeController

    def start(self, *, context: ArtifactCommandContext, acquisition_id: UUID) -> Any:
        self.safe_mode.require(SafeModeCapability.PARSER_WORKERS)
        return self.service.start(context=context, acquisition_id=acquisition_id)

    def status(self, *, context: ArtifactCommandContext, acquisition_id: UUID) -> Any:
        return self.service.status(context=context, acquisition_id=acquisition_id)

    def start_indexing(self, *, context: ArtifactCommandContext, chunk_set_id: str) -> Any:
        self.safe_mode.require(SafeModeCapability.MODELS)
        return self.service.start_indexing(context=context, chunk_set_id=chunk_set_id)

    def __getattr__(self, name: str) -> Any:
        return getattr(self.service, name)


@dataclass(frozen=True, slots=True)
class DocumentIngestionServices:
    admission_service: DocumentAdmissionService
    staging_area: ImportStagingArea
    processing_service: SafeModeProcessingService | DocumentProcessingService
    safe_mode: SafeModeController

    def __post_init__(self) -> None:
        if not isinstance(self.processing_service, SafeModeProcessingService):
            object.__setattr__(
                self,
                "processing_service",
                SafeModeProcessingService(self.processing_service, self.safe_mode),
            )

    @classmethod
    def from_environment(
        cls,
        *,
        environ: Mapping[str, str] | None = None,
        database_conninfo: str | None = None,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
        staging_namespace: Literal["api", "cli"] = "api",
        safe_mode: SafeModeController | None = None,
    ) -> "DocumentIngestionServices":
        values = os.environ if environ is None else environ
        paths = RuntimePaths.from_environment(environ=values)
        resources = RuntimeResources.resolve(
            environ=values,
            development_fallback=Path(__file__).resolve().parents[4],
        )
        staging_parent = paths.data_root / "staging"
        staging_names = {"api": "imports", "cli": "cli-imports"}
        try:
            staging_name = staging_names[staging_namespace]
        except KeyError as error:
            raise ValueError("unsupported ingestion staging namespace") from error
        staging_root = staging_parent / staging_name
        RuntimePaths._ensure_owner_private_directory(staging_parent)
        RuntimePaths._ensure_owner_private_directory(staging_root)

        socket_directory = paths.data_root / "postgres" / "socket"
        conninfo = database_conninfo or (
            f"host='{socket_directory}' port=5432 user='atlas' dbname='atlas'"
        )
        settings = DatabaseSettings.from_conninfo(
            conninfo,
            connect_timeout_seconds=_DATABASE_CONNECT_TIMEOUT_SECONDS,
            statement_timeout_ms=_DATABASE_STATEMENT_TIMEOUT_MS,
            lock_timeout_ms=_DATABASE_LOCK_TIMEOUT_MS,
            transaction_timeout_ms=_DATABASE_TRANSACTION_TIMEOUT_MS,
        )
        database = PostgresDatabase(settings)
        controller = safe_mode or runtime_safe_mode(environ=values)
        apply_or_verify_migrations(
            MigrationRunner(database, paths.migration_root),
            controller,
        )
        artifact_store = ContentAddressedArtifactStore(paths.artifact_root)
        artifact_repository = ArtifactRepository(database, artifact_store)
        acquisition_repository = AcquisitionRepository(database)
        processing_repository = DocumentProcessingRepository(database)
        admission_service = DocumentAdmissionService(
            artifact_store=artifact_store,
            artifact_repository=artifact_repository,
            acquisition_repository=acquisition_repository,
            clock=clock,
        )
        document_worker = DocumentWorkerRunner(profile_template=resources.document_worker_profile)
        preflight = PreflightService(
            admissions=acquisition_repository,
            processing=processing_repository,
            runner=document_worker,
        )
        parser = ParserService(
            admissions=acquisition_repository,
            processing=processing_repository,
            runner=document_worker,
        )
        canonicalizer = CanonicalizationService(
            admissions=acquisition_repository,
            processing=processing_repository,
            artifacts=artifact_repository,
            store=artifact_store,
        )
        processing_root = paths.data_root / "document-processing"
        RuntimePaths._ensure_owner_private_directory(processing_root)
        processing_service = DocumentProcessingService(
            admissions=acquisition_repository,
            processing=processing_repository,
            artifacts=artifact_repository,
            store=artifact_store,
            preflight=preflight,
            parser=parser,
            canonicalizer=canonicalizer,
            run_root=processing_root,
        )
        return cls(
            admission_service=admission_service,
            staging_area=ImportStagingArea(staging_root),
            processing_service=processing_service,
            safe_mode=controller,
        )
