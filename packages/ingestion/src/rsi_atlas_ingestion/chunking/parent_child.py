"""Parent-child hierarchical chunking (development production-policy core)."""

from __future__ import annotations

from rsi_atlas_contracts import (
    CanonicalDocument,
    Chunk,
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
    CHILD_TOKEN_TARGET,
    CHUNK_CONFIGURATION_HASH,
    FlatElement,
    approximate_token_count,
    flatten_elements,
    join_texts,
    sorted_pages,
)


def chunk_parent_child(
    document: CanonicalDocument,
    *,
    document_version_id: str,
    canonical_content_hash: str,
    child_max_tokens: int = CHILD_TOKEN_TARGET,
) -> ChunkSet:
    strategy = ChunkStrategyIdentity(
        family=ChunkStrategyFamily.PARENT_CHILD,
        strategy_id="parent_child",
        version="dev-1",
        configuration_hash=CHUNK_CONFIGURATION_HASH,
    )
    key = chunk_set_key(document_version_id=document_version_id, strategy=strategy)
    elements = flatten_elements(document)
    if not elements:
        raise ValueError("canonical document has no elements to chunk")

    chunks: list[Chunk] = []
    relationships: list[ChunkRelationship] = []
    ordinal = 0
    section_complete = 0

    for section_elements in _sections(elements):
        headings = [item for item in section_elements if item.role == "heading"]
        body = [item for item in section_elements if item.role != "heading"]
        if not body and headings:
            body = headings
            headings = []

        child_chunks, ordinal = _pack_children(
            body,
            key=key,
            start_ordinal=ordinal,
            max_tokens=child_max_tokens,
        )
        chunks.extend(child_chunks)

        parent_source = headings + body if headings else body
        parent_text = join_texts([item.text for item in parent_source])
        parent = build_chunk(
            chunk_set_key_value=key,
            ordinal=ordinal,
            source_element_ids=tuple(item.element_id for item in parent_source),
            text=parent_text,
            token_count=approximate_token_count(parent_text),
            page_numbers=sorted_pages([item.page_number for item in parent_source]),
            metadata={"family": "parent_child", "role": "parent"},
        )
        chunks.append(parent)
        ordinal += 1
        section_complete += 1
        for child in child_chunks:
            relationships.append(
                ChunkRelationship(
                    kind=ChunkRelationshipKind.CHILD,
                    from_chunk_id=parent.chunk_id,
                    to_chunk_id=child.chunk_id,
                )
            )
            relationships.append(
                ChunkRelationship(
                    kind=ChunkRelationshipKind.PARENT,
                    from_chunk_id=child.chunk_id,
                    to_chunk_id=parent.chunk_id,
                )
            )

    built = tuple(chunks)
    return build_chunk_set(
        document_version_id=document_version_id,
        canonical_content_hash=canonical_content_hash,
        strategy=strategy,
        chunks=built,
        relationships=tuple(relationships),
        quality=measure_chunk_set_quality(
            built,
            section_complete_count=section_complete,
        ),
    )


def _pack_children(
    body: list[FlatElement],
    *,
    key: str,
    start_ordinal: int,
    max_tokens: int,
) -> tuple[list[Chunk], int]:
    children: list[Chunk] = []
    bucket: list[FlatElement] = []
    bucket_tokens = 0
    ordinal = start_ordinal

    def flush() -> None:
        nonlocal bucket, bucket_tokens, ordinal
        if not bucket:
            return
        text = join_texts([item.text for item in bucket])
        children.append(
            build_chunk(
                chunk_set_key_value=key,
                ordinal=ordinal,
                source_element_ids=tuple(item.element_id for item in bucket),
                text=text,
                token_count=approximate_token_count(text),
                page_numbers=sorted_pages([item.page_number for item in bucket]),
                metadata={"family": "parent_child", "role": "child"},
            )
        )
        ordinal += 1
        bucket = []
        bucket_tokens = 0

    for element in body:
        tokens = approximate_token_count(element.text)
        if bucket and bucket_tokens + tokens > max_tokens:
            flush()
        bucket.append(element)
        bucket_tokens += tokens
        if bucket_tokens >= max_tokens:
            flush()
    flush()
    return children, ordinal


def _sections(elements: tuple[FlatElement, ...]) -> list[list[FlatElement]]:
    sections: list[list[FlatElement]] = []
    current: list[FlatElement] = []
    for element in elements:
        if element.role == "heading" and current:
            sections.append(current)
            current = [element]
        else:
            current.append(element)
    if current:
        sections.append(current)
    return sections
