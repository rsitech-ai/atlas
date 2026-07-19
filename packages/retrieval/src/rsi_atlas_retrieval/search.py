"""Active-only hybrid candidate generation (dense + lexical + exact)."""

from __future__ import annotations

import re
from hashlib import sha256
from uuid import UUID

from rsi_atlas_contracts import (
    EvidenceCandidate,
    EvidenceItemKind,
    RetrievalDataPlane,
    evidence_candidate_id,
)
from rsi_atlas_contracts.artifact import ArtifactCommandContext
from rsi_atlas_storage.document_processing_repository import DocumentProcessingRepository

_EVM_ADDRESS = re.compile(r"\b0x[a-fA-F0-9]{40}\b")


class HybridCandidateGenerator:
    """Generate ranked EvidenceCandidate lists from active publications only."""

    def __init__(self, *, processing: DocumentProcessingRepository) -> None:
        self._processing = processing

    def generate_lexical(
        self,
        *,
        context: ArtifactCommandContext,
        document_version_id: str,
        chunk_set_id: str,
        query_text: str,
        top_k: int = 40,
    ) -> tuple[EvidenceCandidate, ...]:
        rows = self._processing.search_lexical_active_ranked(
            context=context,
            document_version_id=document_version_id,
            chunk_set_id=chunk_set_id,
            query=query_text,
            top_k=top_k,
        )
        return self._rows_to_candidates(
            rows=rows,
            document_version_id=document_version_id,
            chunk_set_id=chunk_set_id,
            data_plane=RetrievalDataPlane.LEXICAL,
        )

    def generate_dense(
        self,
        *,
        context: ArtifactCommandContext,
        document_version_id: str,
        chunk_set_id: str,
        query_vector: str,
        top_k: int = 40,
    ) -> tuple[EvidenceCandidate, ...]:
        rows = self._processing.search_dense_active_ranked(
            context=context,
            document_version_id=document_version_id,
            chunk_set_id=chunk_set_id,
            query_vector=query_vector,
            top_k=top_k,
        )
        return self._rows_to_candidates(
            rows=rows,
            document_version_id=document_version_id,
            chunk_set_id=chunk_set_id,
            data_plane=RetrievalDataPlane.DENSE_DOCUMENT,
        )

    def generate_exact(
        self,
        *,
        context: ArtifactCommandContext,
        document_version_id: str,
        chunk_set_id: str,
        query_text: str,
        top_k: int = 200,
    ) -> tuple[EvidenceCandidate, ...]:
        identifiers = _extract_identifiers(query_text)
        if not identifiers:
            return ()
        merged: list[dict[str, object]] = []
        seen: set[str] = set()
        for identifier in identifiers:
            rows = self._processing.search_exact_active_ranked(
                context=context,
                document_version_id=document_version_id,
                chunk_set_id=chunk_set_id,
                identifier_value=identifier,
                top_k=top_k,
            )
            for row in rows:
                chunk_id = str(row["chunk_id"])
                if chunk_id in seen:
                    continue
                seen.add(chunk_id)
                merged.append(row)
        return self._rows_to_candidates(
            rows=merged,
            document_version_id=document_version_id,
            chunk_set_id=chunk_set_id,
            data_plane=RetrievalDataPlane.EXACT_IDENTIFIER,
        )

    def _rows_to_candidates(
        self,
        *,
        rows: list[dict[str, object]],
        document_version_id: str,
        chunk_set_id: str,
        data_plane: RetrievalDataPlane,
    ) -> tuple[EvidenceCandidate, ...]:
        candidates: list[EvidenceCandidate] = []
        for rank, row in enumerate(rows, start=1):
            body = str(row["body"])
            preview = body if len(body) <= 500 else body[:497] + "..."
            excerpt_hash = sha256(body.encode("utf-8")).hexdigest()
            index_version_id = row["index_version_id"]
            if not isinstance(index_version_id, UUID):
                raise TypeError("index_version_id must be a UUID")
            candidate = EvidenceCandidate(
                candidate_id=evidence_candidate_id(
                    chunk_id=str(row["chunk_id"]),
                    data_plane=data_plane,
                    index_version_id=index_version_id,
                    rank=rank,
                ),
                chunk_id=str(row["chunk_id"]),
                document_version_id=document_version_id,
                chunk_set_id=chunk_set_id,
                publication_id=str(row["publication_id"]),
                index_version_id=index_version_id,
                data_plane=data_plane,
                item_kind=EvidenceItemKind.SOURCE_CONTENT,
                raw_score=float(row["score"]),  # type: ignore[arg-type]
                rank=rank,
                reliability_score=1.0 if data_plane is RetrievalDataPlane.EXACT_IDENTIFIER else 0.8,
                excerpt_hash=excerpt_hash,
                text_preview=preview,
            )
            candidates.append(candidate)
        return tuple(candidates)


def _extract_identifiers(text: str) -> tuple[str, ...]:
    values: list[str] = []
    seen: set[str] = set()
    for match in _EVM_ADDRESS.finditer(text):
        value = match.group(0).lower()
        if value not in seen:
            seen.add(value)
            values.append(value)
    return tuple(values)


def vector_literal(vector: tuple[float, ...]) -> str:
    return "[" + ",".join(repr(component) for component in vector) + "]"
