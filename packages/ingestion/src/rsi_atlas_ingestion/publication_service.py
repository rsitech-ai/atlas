"""Atomically activate staged retrieval indexes."""

from __future__ import annotations

from datetime import UTC, datetime
from json import dumps
from uuid import UUID, uuid4

from rsi_atlas_contracts import (
    ArtifactCommandContext,
    DocumentProcessingLifecycle,
    RetrievalPublicationManifestDraft,
    publication_identifier,
)
from rsi_atlas_storage.document_processing_repository import DocumentProcessingRepository


class PublicationError(ValueError):
    """Raised when publication activation fails closed."""


class PublicationService:
    """Activate a staging index version so it becomes the searchable pointer."""

    def __init__(self, *, processing: DocumentProcessingRepository) -> None:
        self._processing = processing

    def activate(
        self,
        *,
        context: ArtifactCommandContext,
        index_version_id: UUID,
        now: datetime | None = None,
    ) -> dict[str, object]:
        recorded_at = now or datetime.now(UTC)
        staged = self._processing.get_retrieval_index_version(
            context=context, index_version_id=index_version_id
        )
        if staged is None:
            raise PublicationError("index version not found")
        if staged["status"] == "active":
            existing = self._processing.get_retrieval_publication_manifest(
                context=context,
                index_version_id=index_version_id,
                lifecycle=DocumentProcessingLifecycle.PUBLISHED,
            )
            if existing is None:
                raise PublicationError("published manifest missing for active version")
            return {
                "index_version_id": str(index_version_id),
                "publication_id": existing["publication_id"],
                "status": "active",
                "searchable": True,
            }
        if staged["status"] != "staging":
            raise PublicationError(f"index version status is {staged['status']}")

        validated = self._processing.get_retrieval_publication_manifest(
            context=context,
            index_version_id=index_version_id,
            lifecycle=DocumentProcessingLifecycle.INDEX_VALIDATED,
        )
        if validated is None:
            raise PublicationError("index_validated manifest missing")

        dense_count = self._processing.count_dense_rows(
            context=context, index_version_id=index_version_id
        )
        lexical_count = self._processing.count_lexical_rows(
            context=context, index_version_id=index_version_id
        )
        if (
            dense_count != staged["dense_cardinality"]
            or lexical_count != staged["lexical_cardinality"]
        ):
            raise PublicationError("staging cardinality verification failed")

        # JSON round-trip: stored manifests are jsonb; strict models require JSON coercion.
        draft = RetrievalPublicationManifestDraft.model_validate_json(dumps(validated))
        published_id = publication_identifier(
            document_version_id=draft.document_version_id,
            chunk_set_id=draft.chunk_set_id,
            embedding_set_id=draft.embedding_set.embedding_set_id,
            index_bundle=draft.index_bundle,
            lifecycle=DocumentProcessingLifecycle.PUBLISHED,
        )
        published_manifest = RetrievalPublicationManifestDraft(
            manifest_id=uuid4(),
            publication_id=published_id,
            context=draft.context,
            acquisition_id=draft.acquisition_id,
            document_version_id=draft.document_version_id,
            chunk_set_id=draft.chunk_set_id,
            embedding_set=draft.embedding_set,
            index_bundle=draft.index_bundle,
            dense_index_artifact=draft.dense_index_artifact,
            lexical_index_artifact=draft.lexical_index_artifact,
            chunk_count=draft.chunk_count,
            lifecycle=DocumentProcessingLifecycle.PUBLISHED,
            searchable=True,
            recorded_at=recorded_at,
            warnings=draft.warnings,
        )
        self._processing.activate_retrieval_publication(
            context=context,
            index_version_id=index_version_id,
            manifest=published_manifest,
            recorded_at=recorded_at,
        )
        return {
            "index_version_id": str(index_version_id),
            "publication_id": published_manifest.publication_id,
            "status": "active",
            "searchable": True,
            "document_version_id": published_manifest.document_version_id,
            "chunk_set_id": published_manifest.chunk_set_id,
        }

    def rollback(
        self,
        *,
        context: ArtifactCommandContext,
        document_version_id: str,
        chunk_set_id: str,
        now: datetime | None = None,
    ) -> dict[str, object]:
        recorded_at = now or datetime.now(UTC)
        cleared = self._processing.rollback_retrieval_publication(
            context=context,
            document_version_id=document_version_id,
            chunk_set_id=chunk_set_id,
            recorded_at=recorded_at,
        )
        return {
            "document_version_id": document_version_id,
            "chunk_set_id": chunk_set_id,
            "status": "rolled_back" if cleared else "already_inactive",
            "searchable": False,
        }
