"""Chunk strategy registry: five implemented families; others fail closed."""

from __future__ import annotations

from collections.abc import Callable

from rsi_atlas_contracts import (
    IMPLEMENTED_CHUNK_FAMILIES,
    CanonicalDocument,
    ChunkSet,
    ChunkStrategyFamily,
)

from rsi_atlas_ingestion.chunking.fixed_token import chunk_fixed_token
from rsi_atlas_ingestion.chunking.page_based import chunk_page_based
from rsi_atlas_ingestion.chunking.parent_child import chunk_parent_child
from rsi_atlas_ingestion.chunking.recursive import chunk_recursive
from rsi_atlas_ingestion.chunking.table_aware import chunk_table_aware
from rsi_atlas_ingestion.chunking.tokenize import CHUNK_CONFIGURATION_HASH

Chunker = Callable[..., ChunkSet]

_REGISTRY: dict[ChunkStrategyFamily, Chunker] = {
    ChunkStrategyFamily.FIXED_TOKEN: chunk_fixed_token,
    ChunkStrategyFamily.RECURSIVE: chunk_recursive,
    ChunkStrategyFamily.PAGE_BASED: chunk_page_based,
    ChunkStrategyFamily.PARENT_CHILD: chunk_parent_child,
    ChunkStrategyFamily.TABLE_AWARE: chunk_table_aware,
}


class ChunkStrategyNotImplemented(ValueError):
    """Raised when a registered-but-unimplemented family is requested."""


def implemented_families() -> frozenset[str]:
    return IMPLEMENTED_CHUNK_FAMILIES


def chunk_canonical_document(
    document: CanonicalDocument,
    *,
    family: ChunkStrategyFamily,
    document_version_id: str,
    canonical_content_hash: str,
) -> ChunkSet:
    chunker = _REGISTRY.get(family)
    if chunker is None:
        raise ChunkStrategyNotImplemented(
            f"chunk strategy family {family.value!r} is not implemented in Phase 2C"
        )
    return chunker(
        document,
        document_version_id=document_version_id,
        canonical_content_hash=canonical_content_hash,
    )


__all__ = [
    "CHUNK_CONFIGURATION_HASH",
    "ChunkStrategyNotImplemented",
    "chunk_canonical_document",
    "implemented_families",
]
