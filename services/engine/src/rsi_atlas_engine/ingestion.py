import os
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal

from rsi_atlas_ingestion import DocumentAdmissionService
from rsi_atlas_ingestion.canonical_service import CanonicalizationService
from rsi_atlas_ingestion.parser_service import ParserService
from rsi_atlas_ingestion.processing_pipeline import DocumentProcessingService
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

_DATABASE_CONNECT_TIMEOUT_SECONDS = 1
_DATABASE_STATEMENT_TIMEOUT_MS = 10_000
_DATABASE_LOCK_TIMEOUT_MS = 5_000
_DATABASE_TRANSACTION_TIMEOUT_MS = 15_000


@dataclass(frozen=True, slots=True)
class DocumentIngestionServices:
    admission_service: DocumentAdmissionService
    staging_area: ImportStagingArea
    processing_service: DocumentProcessingService

    @classmethod
    def from_environment(
        cls,
        *,
        environ: Mapping[str, str] | None = None,
        database_conninfo: str | None = None,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
        staging_namespace: Literal["api", "cli"] = "api",
    ) -> "DocumentIngestionServices":
        values = os.environ if environ is None else environ
        paths = RuntimePaths.from_environment(environ=values)
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
        MigrationRunner(database, paths.migration_root).apply_all()
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
        parser = ParserService(
            admissions=acquisition_repository,
            processing=processing_repository,
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
            parser=parser,
            canonicalizer=canonicalizer,
            run_root=processing_root,
        )
        return cls(
            admission_service=admission_service,
            staging_area=ImportStagingArea(staging_root),
            processing_service=processing_service,
        )
