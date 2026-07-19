"""Recursive heading → paragraph → sentence packing."""

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
    split_sentences,
)


def chunk_recursive(
    document: CanonicalDocument,
    *,
    document_version_id: str,
    canonical_content_hash: str,
    max_tokens: int = CHILD_TOKEN_TARGET,
) -> ChunkSet:
    strategy = ChunkStrategyIdentity(
        family=ChunkStrategyFamily.RECURSIVE,
        strategy_id="recursive",
        version="dev-1",
        configuration_hash=CHUNK_CONFIGURATION_HASH,
    )
    key = chunk_set_key(document_version_id=document_version_id, strategy=strategy)
    elements = flatten_elements(document)
    if not elements:
        raise ValueError("canonical document has no elements to chunk")

    units = _recursive_units(elements)
    chunks = []
    bucket_text: list[str] = []
    bucket_ids: list[str] = []
    bucket_pages: set[int] = set()
    bucket_tokens = 0
    ordinal = 0

    def flush() -> None:
        nonlocal bucket_text, bucket_ids, bucket_pages, bucket_tokens, ordinal
        if not bucket_text:
            return
        text = join_texts(bucket_text)
        chunks.append(
            build_chunk(
                chunk_set_key_value=key,
                ordinal=ordinal,
                source_element_ids=tuple(dict.fromkeys(bucket_ids)),
                text=text,
                token_count=approximate_token_count(text),
                page_numbers=sorted_pages(bucket_pages),
                metadata={"family": "recursive"},
            )
        )
        ordinal += 1
        bucket_text = []
        bucket_ids = []
        bucket_pages = set()
        bucket_tokens = 0

    for unit_text, element_id, page_number in units:
        tokens = approximate_token_count(unit_text)
        if bucket_text and bucket_tokens + tokens > max_tokens:
            flush()
        if tokens > max_tokens:
            # Oversized unit becomes its own chunk (soft development threshold).
            flush()
            chunks.append(
                build_chunk(
                    chunk_set_key_value=key,
                    ordinal=ordinal,
                    source_element_ids=(element_id,),
                    text=unit_text,
                    token_count=tokens,
                    page_numbers=(page_number,),
                    metadata={"family": "recursive", "oversized": "true"},
                )
            )
            ordinal += 1
            continue
        bucket_text.append(unit_text)
        bucket_ids.append(element_id)
        bucket_pages.add(page_number)
        bucket_tokens += tokens
    flush()

    built = tuple(chunks)
    return build_chunk_set(
        document_version_id=document_version_id,
        canonical_content_hash=canonical_content_hash,
        strategy=strategy,
        chunks=built,
        quality=measure_chunk_set_quality(built),
    )


def _recursive_units(elements: tuple[FlatElement, ...]) -> list[tuple[str, str, int]]:
    units: list[tuple[str, str, int]] = []
    for element in elements:
        if element.role == "heading":
            units.append((element.text, element.element_id, element.page_number))
            continue
        sentences = split_sentences(element.text)
        if len(sentences) > 1:
            for sentence in sentences:
                units.append((sentence, element.element_id, element.page_number))
        else:
            units.append((element.text, element.element_id, element.page_number))
    return units
