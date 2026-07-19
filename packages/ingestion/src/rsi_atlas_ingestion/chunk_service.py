"""CAS-then-manifest persistence for Phase 2C chunk sets."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from uuid import UUID, uuid4

from rsi_atlas_contracts import (
    ArtifactCommandContext,
    ArtifactDescriptor,
    ArtifactIntegrityError,
    CanonicalDocument,
    ChunkSet,
    ChunkSetManifestDraft,
    ChunkStrategyFamily,
    DocumentProcessingLifecycle,
)
from rsi_atlas_storage import ContentAddressedArtifactStore
from rsi_atlas_storage.artifact_repository import ArtifactRepository
from rsi_atlas_storage.document_processing_repository import DocumentProcessingRepository

from rsi_atlas_ingestion.chunking import chunk_canonical_document


class ChunkPersistenceError(ValueError):
    """Raised when chunk set bytes cannot be persisted fail-closed."""


class ChunkService:
    """Chunk a canonical document and persist one append-only ChunkSet per family."""

    def __init__(
        self,
        *,
        processing: DocumentProcessingRepository,
        artifacts: ArtifactRepository,
        store: ContentAddressedArtifactStore,
    ) -> None:
        self._processing = processing
        self._artifacts = artifacts
        self._store = store

    def chunk_and_persist(
        self,
        *,
        context: ArtifactCommandContext,
        acquisition_id: UUID,
        document_version_id: str,
        family: ChunkStrategyFamily,
        document: CanonicalDocument,
        canonical_content_hash: str,
        now: datetime | None = None,
    ) -> ChunkSet:
        recorded_at = now or datetime.now(UTC)
        chunk_set = chunk_canonical_document(
            document,
            family=family,
            document_version_id=document_version_id,
            canonical_content_hash=canonical_content_hash,
        )
        payload = chunk_set.canonical_json_bytes()
        content_hash = hashlib.sha256(payload).hexdigest()
        if content_hash != chunk_set.content_hash():
            raise ChunkPersistenceError("chunk_set_digest_mismatch")
        descriptor = self._store.put_bytes(
            payload,
            media_type="application/vnd.rsi-atlas.chunk-set+json",
            context=context,
        )
        try:
            verified = self._store.verify(descriptor.artifact_id, context=context)
        except ArtifactIntegrityError as error:
            raise ChunkPersistenceError("chunk_set_cas_corrupt") from error
        if verified.digest != content_hash:
            raise ChunkPersistenceError("chunk_set_cas_digest_mismatch")
        self._artifacts.register(context=context, descriptor=descriptor)

        manifest = ChunkSetManifestDraft(
            manifest_id=uuid4(),
            context=context,
            acquisition_id=acquisition_id,
            document_version_id=document_version_id,
            canonical_content_hash=canonical_content_hash,
            chunk_set=chunk_set,
            chunk_set_content_hash=content_hash,
            chunk_set_artifact=descriptor,
            lifecycle=DocumentProcessingLifecycle.CHUNKED,
            recorded_at=recorded_at,
        )
        self._processing.commit_chunk_set_manifest(context=context, manifest=manifest)
        return chunk_set

    def chunk_all_implemented(
        self,
        *,
        context: ArtifactCommandContext,
        acquisition_id: UUID,
        document_version_id: str,
        document: CanonicalDocument,
        canonical_content_hash: str,
        now: datetime | None = None,
    ) -> tuple[ChunkSet, ...]:
        families = (
            ChunkStrategyFamily.FIXED_TOKEN,
            ChunkStrategyFamily.RECURSIVE,
            ChunkStrategyFamily.PAGE_BASED,
            ChunkStrategyFamily.PARENT_CHILD,
            ChunkStrategyFamily.TABLE_AWARE,
        )
        return tuple(
            self.chunk_and_persist(
                context=context,
                acquisition_id=acquisition_id,
                document_version_id=document_version_id,
                family=family,
                document=document,
                canonical_content_hash=canonical_content_hash,
                now=now,
            )
            for family in families
        )

    def load_chunk_set(
        self,
        *,
        context: ArtifactCommandContext,
        chunk_set_id: str,
    ) -> ChunkSet:
        row = self._processing.get_chunk_set_manifest(context=context, chunk_set_id=chunk_set_id)
        if row is None:
            raise LookupError("chunk set not found")
        descriptor = ArtifactDescriptor.model_validate(row["chunk_set_artifact"])
        try:
            payload = self._store.read_bytes(descriptor.artifact_id, context=context)
        except ArtifactIntegrityError as error:
            raise ChunkPersistenceError("chunk_set_bytes_corrupt") from error
        if hashlib.sha256(payload).hexdigest() != descriptor.digest:
            raise ChunkPersistenceError("chunk_set_bytes_corrupt")
        return ChunkSet.model_validate_json(payload)
