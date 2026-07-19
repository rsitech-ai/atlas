"""Page-based chunking: one retrieval unit per canonical page."""

from __future__ import annotations

from rsi_atlas_contracts import (
    CanonicalDocument,
    ChunkSet,
    ChunkStrategyFamily,
    ChunkStrategyIdentity,
    build_chunk,
    build_chunk_set,
    chunk_set_key,
    measure_chunk_set_quality,
)

from rsi_atlas_ingestion.chunking.tokenize import (
    CHUNK_CONFIGURATION_HASH,
    FlatElement,
    approximate_token_count,
    flatten_elements,
    join_texts,
)


def chunk_page_based(
    document: CanonicalDocument,
    *,
    document_version_id: str,
    canonical_content_hash: str,
) -> ChunkSet:
    strategy = ChunkStrategyIdentity(
        family=ChunkStrategyFamily.PAGE_BASED,
        strategy_id="page_based",
        version="dev-1",
        configuration_hash=CHUNK_CONFIGURATION_HASH,
    )
    key = chunk_set_key(document_version_id=document_version_id, strategy=strategy)
    elements = flatten_elements(document)
    if not elements:
        raise ValueError("canonical document has no elements to chunk")

    by_page: dict[int, list[FlatElement]] = {}
    for element in elements:
        by_page.setdefault(element.page_number, []).append(element)

    chunks = []
    for ordinal, page_number in enumerate(sorted(by_page)):
        page_elements = by_page[page_number]
        text = join_texts([item.text for item in page_elements])
        chunks.append(
            build_chunk(
                chunk_set_key_value=key,
                ordinal=ordinal,
                source_element_ids=tuple(item.element_id for item in page_elements),
                text=text,
                token_count=approximate_token_count(text),
                page_numbers=(page_number,),
                metadata={"family": "page_based"},
            )
        )
    built = tuple(chunks)
    return build_chunk_set(
        document_version_id=document_version_id,
        canonical_content_hash=canonical_content_hash,
        strategy=strategy,
        chunks=built,
        quality=measure_chunk_set_quality(built),
    )
