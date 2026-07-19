"""Unit tests for the five Phase 2C chunking families."""

from __future__ import annotations

from decimal import Decimal
from hashlib import sha256

import pytest
from rsi_atlas_contracts import (
    BoundingBox,
    CanonicalDocument,
    CanonicalPage,
    CanonicalTableElement,
    CanonicalTextElement,
    CanonicalTextRole,
    ChunkStrategyFamily,
    CoordinateSystem,
    PageGeometry,
    ParserCandidateIdentity,
    build_canonical_document,
    canonical_element_identifier,
    canonicalization_identifier,
    sha256_text,
)
from rsi_atlas_ingestion.chunking import (
    CHUNK_CONFIGURATION_HASH,
    ChunkStrategyNotImplemented,
    chunk_canonical_document,
    implemented_families,
)

DOCUMENT_VERSION = "canonical:" + ("a" * 64)
CONTENT_HASH = "b" * 64
DIGEST = "c" * 64
BUILD = "d" * 64
CONFIG = "e" * 64
NORMALIZER = "f" * 64
OUTPUT = "1" * 64


def _box(
    *,
    left: str = "0.100000",
    top: str = "0.100000",
    right: str = "0.900000",
    bottom: str = "0.200000",
) -> BoundingBox:
    return BoundingBox(
        coordinate_system=CoordinateSystem.NORMALIZED_TOP_LEFT,
        left=Decimal(left),
        top=Decimal(top),
        right=Decimal(right),
        bottom=Decimal(bottom),
    )


def _raw_box() -> BoundingBox:
    return BoundingBox(
        coordinate_system=CoordinateSystem.PDF_BOTTOM_LEFT_POINTS,
        left=Decimal("72.000000"),
        bottom=Decimal("700.000000"),
        right=Decimal("360.000000"),
        top=Decimal("720.000000"),
    )


def _geometry(page_number: int = 1) -> PageGeometry:
    media = BoundingBox(
        coordinate_system=CoordinateSystem.PDF_BOTTOM_LEFT_POINTS,
        left=Decimal("0.000000"),
        bottom=Decimal("0.000000"),
        right=Decimal("612.000000"),
        top=Decimal("792.000000"),
    )
    return PageGeometry(
        page_number=page_number,
        media_box=media,
        crop_box=media,
        rotation_degrees=0,
    )


def _text(
    *,
    canonicalization_id: str,
    page_number: int,
    reading_order: int,
    text: str,
    role: CanonicalTextRole = CanonicalTextRole.PARAGRAPH,
) -> CanonicalTextElement:
    raw_hash = sha256_text(text)
    box = _box(
        top=f"{0.05 + reading_order * 0.05:.6f}",
        bottom=f"{0.10 + reading_order * 0.05:.6f}",
    )
    span_hash = sha256(f"{OUTPUT}|{page_number}|{reading_order}|{raw_hash}".encode()).hexdigest()
    element_id = canonical_element_identifier(
        canonicalization_id=canonicalization_id,
        page_number=page_number,
        kind="text",
        reading_order=reading_order,
        bounding_box=box,
        raw_text_hash=raw_hash,
    )
    return CanonicalTextElement(
        kind="text",
        role=role,
        canonicalization_id=canonicalization_id,
        element_id=element_id,
        page_number=page_number,
        reading_order=reading_order,
        bounding_box=box,
        raw_bounding_box=_raw_box(),
        raw_text=text,
        raw_text_hash=raw_hash,
        normalized_text=text,
        normalized_text_hash=raw_hash,
        parser_confidence=1.0,
        language="unknown",
        source_output_artifact_digest=OUTPUT,
        source_span_id=f"span_{reading_order:04d}",
        source_span_hash=span_hash,
        source_hash=span_hash,
    )


def _table(
    *,
    canonicalization_id: str,
    page_number: int,
    reading_order: int,
    text: str,
    row_count: int,
    column_count: int,
) -> CanonicalTableElement:
    raw_hash = sha256_text(text)
    box = _box(
        top=f"{0.05 + reading_order * 0.05:.6f}",
        bottom=f"{0.20 + reading_order * 0.05:.6f}",
    )
    span_hash = sha256(
        f"{OUTPUT}|table|{page_number}|{reading_order}|{raw_hash}".encode()
    ).hexdigest()
    element_id = canonical_element_identifier(
        canonicalization_id=canonicalization_id,
        page_number=page_number,
        kind="table",
        reading_order=reading_order,
        bounding_box=box,
        raw_text_hash=raw_hash,
    )
    return CanonicalTableElement(
        kind="table",
        row_count=row_count,
        column_count=column_count,
        canonicalization_id=canonicalization_id,
        element_id=element_id,
        page_number=page_number,
        reading_order=reading_order,
        bounding_box=box,
        raw_bounding_box=_raw_box(),
        raw_text=text,
        raw_text_hash=raw_hash,
        normalized_text=text,
        normalized_text_hash=raw_hash,
        parser_confidence=1.0,
        language="unknown",
        source_output_artifact_digest=OUTPUT,
        source_span_id=f"span_t{reading_order:03d}",
        source_span_hash=span_hash,
        source_hash=span_hash,
    )


def _sample_document() -> CanonicalDocument:
    candidate = ParserCandidateIdentity(
        parser_id="pypdf_tier0",
        name="pypdf",
        version="6.14.2",
        tier=0,
        build_hash=BUILD,
        configuration_hash=CONFIG,
    )
    cid = canonicalization_identifier(
        artifact_digest=DIGEST,
        parser_build_hash=BUILD,
        parser_configuration_hash=CONFIG,
        normalizer_version="nfc-1",
        normalizer_configuration_hash=NORMALIZER,
    )
    page1 = CanonicalPage(
        canonicalization_id=cid,
        source_artifact_digest=DIGEST,
        page_number=1,
        geometry=_geometry(1),
        elements=(
            _text(
                canonicalization_id=cid,
                page_number=1,
                reading_order=0,
                text="Introduction",
                role=CanonicalTextRole.HEADING,
            ),
            _text(
                canonicalization_id=cid,
                page_number=1,
                reading_order=1,
                text="Bitcoin settles every ten minutes on the base layer.",
            ),
            _text(
                canonicalization_id=cid,
                page_number=1,
                reading_order=2,
                text="Ethereum finality depends on checkpoint attestation.",
            ),
        ),
    )
    page2 = CanonicalPage(
        canonicalization_id=cid,
        source_artifact_digest=DIGEST,
        page_number=2,
        geometry=_geometry(2),
        elements=(
            _text(
                canonicalization_id=cid,
                page_number=2,
                reading_order=0,
                text="Token Allocation",
                role=CanonicalTextRole.HEADING,
            ),
            _table(
                canonicalization_id=cid,
                page_number=2,
                reading_order=1,
                text="Bucket\tShare\nTeam\t20%\nCommunity\t40%\nInvestors\t40%",
                row_count=4,
                column_count=2,
            ),
            _text(
                canonicalization_id=cid,
                page_number=2,
                reading_order=2,
                text="Address 0xabc123 remains the treasury signer.",
            ),
        ),
    )
    return build_canonical_document(
        source_artifact_digest=DIGEST,
        candidate=candidate,
        normalizer_version="nfc-1",
        normalizer_configuration_hash=NORMALIZER,
        pages=(page1, page2),
    )


def test_implemented_families_are_exactly_five() -> None:
    assert {
        "fixed_token",
        "recursive",
        "page_based",
        "parent_child",
        "table_aware",
    } == implemented_families()
    expected_hash = sha256(
        b"phase-2c-chunk-dev-1|child=400|parent=900-1800|approx-tokenizer"
    ).hexdigest()
    assert expected_hash == CHUNK_CONFIGURATION_HASH


def test_unimplemented_family_fails_closed() -> None:
    document = _sample_document()
    with pytest.raises(ChunkStrategyNotImplemented):
        chunk_canonical_document(
            document,
            family=ChunkStrategyFamily.LATE_CHUNKING,
            document_version_id=DOCUMENT_VERSION,
            canonical_content_hash=CONTENT_HASH,
        )


@pytest.mark.parametrize(
    "family",
    [
        ChunkStrategyFamily.FIXED_TOKEN,
        ChunkStrategyFamily.RECURSIVE,
        ChunkStrategyFamily.PAGE_BASED,
        ChunkStrategyFamily.PARENT_CHILD,
        ChunkStrategyFamily.TABLE_AWARE,
    ],
)
def test_each_family_is_deterministic_and_preserves_crypto_tokens(
    family: ChunkStrategyFamily,
) -> None:
    document = _sample_document()
    first = chunk_canonical_document(
        document,
        family=family,
        document_version_id=DOCUMENT_VERSION,
        canonical_content_hash=CONTENT_HASH,
    )
    second = chunk_canonical_document(
        document,
        family=family,
        document_version_id=DOCUMENT_VERSION,
        canonical_content_hash=CONTENT_HASH,
    )
    assert first.chunk_set_id == second.chunk_set_id
    assert first.canonical_json_bytes() == second.canonical_json_bytes()
    joined = "\n".join(chunk.text for chunk in first.chunks)
    assert "Bitcoin" in joined
    assert "0xabc123" in joined
    assert "20%" in joined
    element_ids = {element.element_id for page in document.pages for element in page.elements}
    for chunk in first.chunks:
        assert set(chunk.source_element_ids) <= element_ids


def test_page_based_emits_one_chunk_per_page() -> None:
    document = _sample_document()
    result = chunk_canonical_document(
        document,
        family=ChunkStrategyFamily.PAGE_BASED,
        document_version_id=DOCUMENT_VERSION,
        canonical_content_hash=CONTENT_HASH,
    )
    assert result.quality.chunk_count == 2
    assert result.chunks[0].page_numbers == (1,)
    assert result.chunks[1].page_numbers == (2,)


def test_parent_child_emits_relationships() -> None:
    document = _sample_document()
    result = chunk_canonical_document(
        document,
        family=ChunkStrategyFamily.PARENT_CHILD,
        document_version_id=DOCUMENT_VERSION,
        canonical_content_hash=CONTENT_HASH,
    )
    assert result.relationships
    kinds = {rel.kind.value for rel in result.relationships}
    assert "parent" in kinds
    assert "child" in kinds
    assert any(chunk.metadata.get("role") == "parent" for chunk in result.chunks)


def test_table_aware_emits_table_and_row_chunks() -> None:
    document = _sample_document()
    result = chunk_canonical_document(
        document,
        family=ChunkStrategyFamily.TABLE_AWARE,
        document_version_id=DOCUMENT_VERSION,
        canonical_content_hash=CONTENT_HASH,
    )
    roles = [chunk.metadata.get("role") for chunk in result.chunks]
    assert "table" in roles
    assert "row" in roles
    assert any(rel.kind.value == "row_of" for rel in result.relationships)
