"""Table-aware chunking with full-table and row-level projections."""

from __future__ import annotations

from rsi_atlas_contracts import (
    CanonicalDocument,
    ChunkRelationship,
    ChunkRelationshipKind,
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
    sorted_pages,
)


def chunk_table_aware(
    document: CanonicalDocument,
    *,
    document_version_id: str,
    canonical_content_hash: str,
) -> ChunkSet:
    strategy = ChunkStrategyIdentity(
        family=ChunkStrategyFamily.TABLE_AWARE,
        strategy_id="table_aware",
        version="dev-1",
        configuration_hash=CHUNK_CONFIGURATION_HASH,
    )
    key = chunk_set_key(document_version_id=document_version_id, strategy=strategy)
    elements = flatten_elements(document)
    if not elements:
        raise ValueError("canonical document has no elements to chunk")

    chunks = []
    relationships: list[ChunkRelationship] = []
    ordinal = 0
    table_chunks = 0
    non_table_bucket: list[FlatElement] = []

    def flush_non_table() -> None:
        nonlocal non_table_bucket, ordinal
        if not non_table_bucket:
            return
        text = join_texts([item.text for item in non_table_bucket])
        chunks.append(
            build_chunk(
                chunk_set_key_value=key,
                ordinal=ordinal,
                source_element_ids=tuple(item.element_id for item in non_table_bucket),
                text=text,
                token_count=approximate_token_count(text),
                page_numbers=sorted_pages([item.page_number for item in non_table_bucket]),
                metadata={"family": "table_aware", "role": "prose"},
            )
        )
        ordinal += 1
        non_table_bucket = []

    for element in elements:
        if element.kind != "table":
            non_table_bucket.append(element)
            continue
        flush_non_table()
        table_chunk = build_chunk(
            chunk_set_key_value=key,
            ordinal=ordinal,
            source_element_ids=(element.element_id,),
            text=element.text,
            token_count=approximate_token_count(element.text),
            page_numbers=(element.page_number,),
            metadata={"family": "table_aware", "role": "table"},
        )
        chunks.append(table_chunk)
        ordinal += 1
        table_chunks += 1

        rows = _table_rows(element.text)
        header = rows[0] if rows else ""
        body_rows = rows[1:] if len(rows) > 1 else rows
        for row_index, row in enumerate(body_rows):
            row_text = f"{header}\n{row}" if header and row != header else row
            row_chunk = build_chunk(
                chunk_set_key_value=key,
                ordinal=ordinal,
                source_element_ids=(element.element_id,),
                text=row_text,
                token_count=approximate_token_count(row_text),
                page_numbers=(element.page_number,),
                metadata={
                    "family": "table_aware",
                    "role": "row",
                    "row_index": str(row_index),
                },
                contextual_prefix=header or None,
            )
            chunks.append(row_chunk)
            relationships.append(
                ChunkRelationship(
                    kind=ChunkRelationshipKind.ROW_OF,
                    from_chunk_id=row_chunk.chunk_id,
                    to_chunk_id=table_chunk.chunk_id,
                )
            )
            relationships.append(
                ChunkRelationship(
                    kind=ChunkRelationshipKind.TABLE_OF,
                    from_chunk_id=table_chunk.chunk_id,
                    to_chunk_id=row_chunk.chunk_id,
                )
            )
            ordinal += 1
            table_chunks += 1
    flush_non_table()

    built = tuple(chunks)
    return build_chunk_set(
        document_version_id=document_version_id,
        canonical_content_hash=canonical_content_hash,
        strategy=strategy,
        chunks=built,
        relationships=tuple(relationships),
        quality=measure_chunk_set_quality(built, table_chunk_count=table_chunks),
    )


def _table_rows(text: str) -> list[str]:
    rows = [line.strip() for line in text.splitlines() if line.strip()]
    return rows if rows else [text.strip()] if text.strip() else []
