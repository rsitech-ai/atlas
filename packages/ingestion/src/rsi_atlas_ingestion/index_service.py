"""Stage dense + lexical + exact indexes from a persisted ChunkSet."""

from __future__ import annotations

import hashlib
import re
from datetime import UTC, datetime
from json import dumps
from uuid import UUID, uuid4

from rsi_atlas_contracts import (
    ArtifactCommandContext,
    ArtifactDescriptor,
    ArtifactIntegrityError,
    ChunkEmbedding,
    ChunkSet,
    DocumentProcessingLifecycle,
    EmbeddingPromotionClass,
    EmbeddingSet,
    RetrievalIndexBundle,
    RetrievalPublicationManifestDraft,
    embedding_set_identifier,
    publication_identifier,
)
from rsi_atlas_storage import ContentAddressedArtifactStore
from rsi_atlas_storage.artifact_repository import ArtifactRepository
from rsi_atlas_storage.document_processing_repository import DocumentProcessingRepository

from rsi_atlas_ingestion.embedding import DEVELOPMENT_EMBEDDING_MODEL, DeterministicEmbedder
from rsi_atlas_ingestion.embedding.resolve import Embedder

_EVM_ADDRESS = re.compile(r"\b0x[a-fA-F0-9]{40}\b")
_DENSE_MEDIA = "application/vnd.rsi-atlas.dense-index+json"
_LEXICAL_MEDIA = "application/vnd.rsi-atlas.lexical-index+json"
_ALLOWED_PROMOTION = frozenset(
    {
        EmbeddingPromotionClass.DEVELOPMENT_FIXTURE,
        EmbeddingPromotionClass.CANDIDATE,
    }
)


class IndexStagingError(ValueError):
    """Raised when staging indexes fail closed."""


def extract_exact_identifiers(text: str) -> tuple[tuple[str, str], ...]:
    """Return ordered unique (kind, value) identifier hits from chunk text."""
    hits: list[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for match in _EVM_ADDRESS.finditer(text):
        value = match.group(0).lower()
        key = ("evm_address", value)
        if key not in seen:
            seen.add(key)
            hits.append(key)
    return tuple(hits)


def _canonical_json(payload: object) -> bytes:
    return dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def _vector_literal(vector: tuple[float, ...]) -> str:
    return "[" + ",".join(repr(component) for component in vector) + "]"


class IndexService:
    """Build non-searchable staging dense/lexical indexes for one chunk set."""

    def __init__(
        self,
        *,
        processing: DocumentProcessingRepository,
        artifacts: ArtifactRepository,
        store: ContentAddressedArtifactStore,
        embedder: Embedder | None = None,
    ) -> None:
        self._processing = processing
        self._artifacts = artifacts
        self._store = store
        self._embedder = embedder or DeterministicEmbedder()

    def stage_indexes(
        self,
        *,
        context: ArtifactCommandContext,
        acquisition_id: UUID,
        chunk_set_id: str,
        now: datetime | None = None,
    ) -> dict[str, object]:
        recorded_at = now or datetime.now(UTC)
        chunk_set = self._load_chunk_set(context=context, chunk_set_id=chunk_set_id)
        model = self._embedder.model
        if model.promotion_class not in _ALLOWED_PROMOTION:
            raise IndexStagingError("embedding promotion_class not allowed for staging")
        # Fixture path stays pinned; candidate OSS models may diverge from fixture identity.
        if (
            model.promotion_class is EmbeddingPromotionClass.DEVELOPMENT_FIXTURE
            and model != DEVELOPMENT_EMBEDDING_MODEL
        ):
            raise IndexStagingError("unexpected embedding model identity")

        dense_rows: list[dict[str, object]] = []
        lexical_rows: list[dict[str, object]] = []
        exact_rows: list[dict[str, object]] = []
        chunk_embeddings: list[ChunkEmbedding] = []
        for chunk in chunk_set.chunks:
            vector = self._embedder.embed_text(chunk.text)
            dense_rows.append(
                {
                    "chunk_id": chunk.chunk_id,
                    "chunk_text_hash": chunk.text_hash,
                    "ordinal": chunk.ordinal,
                    "vector": list(vector),
                }
            )
            lexical_rows.append(
                {
                    "chunk_id": chunk.chunk_id,
                    "chunk_text_hash": chunk.text_hash,
                    "ordinal": chunk.ordinal,
                    "body": chunk.text,
                }
            )
            for kind, value in extract_exact_identifiers(chunk.text):
                exact_rows.append(
                    {
                        "chunk_id": chunk.chunk_id,
                        "identifier_kind": kind,
                        "identifier_value": value,
                        "ordinal": chunk.ordinal,
                    }
                )
            chunk_embeddings.append(
                ChunkEmbedding(
                    chunk_id=chunk.chunk_id,
                    chunk_text_hash=chunk.text_hash,
                    vector=vector,
                    input_policy_hash=self._embedder.input_policy_hash,
                    model=model,
                )
            )

        dense_bytes = _canonical_json({"rows": dense_rows, "model": model.model_dump(mode="json")})
        lexical_bytes = _canonical_json({"rows": lexical_rows})
        exact_bytes = _canonical_json({"rows": exact_rows})
        dense_hash = hashlib.sha256(dense_bytes).hexdigest()
        lexical_hash = hashlib.sha256(lexical_bytes).hexdigest()
        exact_hash = hashlib.sha256(exact_bytes).hexdigest()

        dense_descriptor = self._store.put_bytes(
            dense_bytes, media_type=_DENSE_MEDIA, context=context
        )
        lexical_descriptor = self._store.put_bytes(
            lexical_bytes, media_type=_LEXICAL_MEDIA, context=context
        )
        self._verify_cas(dense_descriptor, expected=dense_hash, context=context)
        self._verify_cas(lexical_descriptor, expected=lexical_hash, context=context)
        self._artifacts.register(context=context, descriptor=dense_descriptor)
        self._artifacts.register(context=context, descriptor=lexical_descriptor)

        embedding_tuple = tuple(chunk_embeddings)
        embedding_set = EmbeddingSet(
            embedding_set_id=embedding_set_identifier(
                chunk_set_id=chunk_set.chunk_set_id,
                chunk_set_content_hash=chunk_set.content_hash(),
                model=model,
                embeddings=embedding_tuple,
            ),
            chunk_set_id=chunk_set.chunk_set_id,
            chunk_set_content_hash=chunk_set.content_hash(),
            model=model,
            embeddings=embedding_tuple,
        )
        bundle = RetrievalIndexBundle(
            dense_cardinality=len(dense_rows),
            lexical_cardinality=len(lexical_rows),
            exact_identifier_cardinality=len(exact_rows),
            dense_content_hash=dense_hash,
            lexical_content_hash=lexical_hash,
            exact_content_hash=exact_hash,
        )
        if bundle.dense_cardinality != len(chunk_set.chunks):
            raise IndexStagingError("dense cardinality mismatch")
        if bundle.lexical_cardinality != len(chunk_set.chunks):
            raise IndexStagingError("lexical cardinality mismatch")

        publication_id = publication_identifier(
            document_version_id=chunk_set.document_version_id,
            chunk_set_id=chunk_set.chunk_set_id,
            embedding_set_id=embedding_set.embedding_set_id,
            index_bundle=bundle,
            lifecycle=DocumentProcessingLifecycle.INDEX_VALIDATED,
        )
        manifest = RetrievalPublicationManifestDraft(
            manifest_id=uuid4(),
            publication_id=publication_id,
            context=context,
            acquisition_id=acquisition_id,
            document_version_id=chunk_set.document_version_id,
            chunk_set_id=chunk_set.chunk_set_id,
            embedding_set=embedding_set,
            index_bundle=bundle,
            dense_index_artifact=dense_descriptor,
            lexical_index_artifact=lexical_descriptor,
            chunk_count=len(chunk_set.chunks),
            lifecycle=DocumentProcessingLifecycle.INDEX_VALIDATED,
            searchable=False,
            recorded_at=recorded_at,
        )

        dense_literals = [
            {
                "chunk_id": row["chunk_id"],
                "chunk_text_hash": row["chunk_text_hash"],
                "ordinal": row["ordinal"],
                "embedding": _vector_literal(tuple(row["vector"])),  # type: ignore[arg-type]
            }
            for row in dense_rows
        ]
        index_version_id = self._processing.stage_retrieval_index(
            context=context,
            acquisition_id=acquisition_id,
            document_version_id=chunk_set.document_version_id,
            chunk_set_id=chunk_set.chunk_set_id,
            chunk_set_content_hash=chunk_set.content_hash(),
            embedding_model_id=model.model_id,
            embedding_configuration_hash=model.configuration_hash,
            dense_rows=dense_literals,
            lexical_rows=lexical_rows,
            exact_rows=exact_rows,
            dense_content_hash=dense_hash,
            lexical_content_hash=lexical_hash,
            exact_content_hash=exact_hash,
            dense_artifact_id=str(dense_descriptor.artifact_id),
            lexical_artifact_id=str(lexical_descriptor.artifact_id),
            manifest=manifest,
            recorded_at=recorded_at,
        )
        return {
            "index_version_id": str(index_version_id),
            "publication_id": publication_id,
            "chunk_set_id": chunk_set.chunk_set_id,
            "document_version_id": chunk_set.document_version_id,
            "status": "staging",
            "searchable": False,
            "dense_cardinality": bundle.dense_cardinality,
            "lexical_cardinality": bundle.lexical_cardinality,
            "exact_identifier_cardinality": bundle.exact_identifier_cardinality,
            "embedding_model_id": model.model_id,
        }

    def _load_chunk_set(self, *, context: ArtifactCommandContext, chunk_set_id: str) -> ChunkSet:
        row = self._processing.get_chunk_set_manifest(context=context, chunk_set_id=chunk_set_id)
        if row is None:
            raise IndexStagingError("chunk set not found")
        descriptor = ArtifactDescriptor.model_validate(row["chunk_set_artifact"])
        try:
            payload = self._store.read_bytes(descriptor.artifact_id, context=context)
        except ArtifactIntegrityError as error:
            raise IndexStagingError("chunk_set_bytes_corrupt") from error
        if hashlib.sha256(payload).hexdigest() != descriptor.digest:
            raise IndexStagingError("chunk_set_bytes_corrupt")
        return ChunkSet.model_validate_json(payload)

    def _verify_cas(
        self,
        descriptor: ArtifactDescriptor,
        *,
        expected: str,
        context: ArtifactCommandContext,
    ) -> None:
        try:
            verified = self._store.verify(descriptor.artifact_id, context=context)
        except ArtifactIntegrityError as error:
            raise IndexStagingError("index_cas_corrupt") from error
        if verified.digest != expected:
            raise IndexStagingError("index_cas_digest_mismatch")
