"""Fixed-token packing over canonical element streams."""

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
    CHILD_TOKEN_TARGET,
    CHUNK_CONFIGURATION_HASH,
    FlatElement,
    approximate_token_count,
    flatten_elements,
    join_texts,
    sorted_pages,
)


def chunk_fixed_token(
    document: CanonicalDocument,
    *,
    document_version_id: str,
    canonical_content_hash: str,
    max_tokens: int = CHILD_TOKEN_TARGET,
) -> ChunkSet:
    strategy = ChunkStrategyIdentity(
        family=ChunkStrategyFamily.FIXED_TOKEN,
        strategy_id="fixed_token",
        version="dev-1",
        configuration_hash=CHUNK_CONFIGURATION_HASH,
    )
    key = chunk_set_key(document_version_id=document_version_id, strategy=strategy)
    elements = flatten_elements(document)
    if not elements:
        raise ValueError("canonical document has no elements to chunk")

    chunks = []
    bucket_elements: list[FlatElement] = []
    bucket_tokens = 0
    ordinal = 0

    def flush() -> None:
        nonlocal bucket_elements, bucket_tokens, ordinal
        if not bucket_elements:
            return
        text = join_texts([item.text for item in bucket_elements])
        chunks.append(
            build_chunk(
                chunk_set_key_value=key,
                ordinal=ordinal,
                source_element_ids=tuple(item.element_id for item in bucket_elements),
                text=text,
                token_count=approximate_token_count(text),
                page_numbers=sorted_pages([item.page_number for item in bucket_elements]),
                metadata={"family": "fixed_token"},
            )
        )
        ordinal += 1
        bucket_elements = []
        bucket_tokens = 0

    for element in elements:
        tokens = approximate_token_count(element.text)
        if bucket_elements and bucket_tokens + tokens > max_tokens:
            flush()
        bucket_elements.append(element)
        bucket_tokens += tokens
        if bucket_tokens >= max_tokens:
            flush()
    flush()

    built = tuple(chunks)
    return build_chunk_set(
        document_version_id=document_version_id,
        canonical_content_hash=canonical_content_hash,
        strategy=strategy,
        chunks=built,
        quality=measure_chunk_set_quality(built),
    )
