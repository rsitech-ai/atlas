"""Pure canonicalization unit tests."""

from __future__ import annotations

import hashlib
import os
from decimal import Decimal
from pathlib import Path

import pytest
from rsi_atlas_contracts import BoundingBox, CoordinateSystem, ParserCandidateIdentity
from rsi_atlas_document_worker.parsers import PyPdfParserCandidate
from rsi_atlas_ingestion.canonicalization import (
    NORMALIZER_CONFIGURATION_HASH,
    NORMALIZER_VERSION,
    CanonicalizationError,
    canonicalize_parse_result,
    normalize_text,
    pdf_box_to_normalized,
)
from rsi_atlas_ingestion.parser_service import _PARSER_CONFIG

FIXTURE = Path("packages/ingestion/benchmarks/pdf/fixtures/crypto_technical_three_page.pdf")
ROTATED = Path("packages/ingestion/benchmarks/pdf/fixtures/rotated_crop_box.pdf")
_CANDIDATE = ParserCandidateIdentity(
    parser_id="pypdf_tier0",
    name="pypdf",
    version="6.14.2",
    tier=0,
    build_hash=hashlib.sha256(b"pypdf-6.14.2-tier0-parse").hexdigest(),
    configuration_hash=_PARSER_CONFIG,
)


def _parse(path: Path) -> dict:
    fd = os.open(path, os.O_RDONLY)
    try:
        return PyPdfParserCandidate().parse(artifact_fd=fd)
    finally:
        os.close(fd)


def test_normalize_text_is_nfc() -> None:
    assert normalize_text("e\u0301") == "é"


def test_pdf_box_normalization_rotation_zero() -> None:
    crop = BoundingBox(
        coordinate_system=CoordinateSystem.PDF_BOTTOM_LEFT_POINTS,
        left=Decimal("0.000000"),
        bottom=Decimal("0.000000"),
        right=Decimal("100.000000"),
        top=Decimal("200.000000"),
    )
    raw = BoundingBox(
        coordinate_system=CoordinateSystem.PDF_BOTTOM_LEFT_POINTS,
        left=Decimal("10.000000"),
        bottom=Decimal("40.000000"),
        right=Decimal("90.000000"),
        top=Decimal("160.000000"),
    )
    norm = pdf_box_to_normalized(raw, crop=crop, rotation_degrees=0)
    assert norm.left == Decimal("0.100000")
    assert norm.right == Decimal("0.900000")
    assert norm.top == Decimal("0.200000")
    assert norm.bottom == Decimal("0.800000")


def test_canonicalize_born_digital_is_deterministic() -> None:
    parse_result = _parse(FIXTURE)
    digest = "a" * 64
    output = "b" * 64
    first, _ = canonicalize_parse_result(
        parse_result=parse_result,
        source_artifact_digest=digest,
        candidate=_CANDIDATE,
        source_output_artifact_digest=output,
    )
    second, _ = canonicalize_parse_result(
        parse_result=parse_result,
        source_artifact_digest=digest,
        candidate=_CANDIDATE,
        source_output_artifact_digest=output,
    )
    assert first.canonical_json_bytes() == second.canonical_json_bytes()
    assert first.normalizer_version == NORMALIZER_VERSION
    assert first.normalizer_configuration_hash == NORMALIZER_CONFIGURATION_HASH
    assert len(first.pages) == 3
    assert all(page.elements for page in first.pages)
    joined = "\n".join(element.raw_text for page in first.pages for element in page.elements)
    assert joined.strip()


def test_canonicalize_preserves_rotated_crop_text() -> None:
    parse_result = _parse(ROTATED)
    document, _ = canonicalize_parse_result(
        parse_result=parse_result,
        source_artifact_digest="c" * 64,
        candidate=_CANDIDATE,
        source_output_artifact_digest="d" * 64,
    )
    text = "\n".join(element.raw_text for page in document.pages for element in page.elements)
    assert "Rotated crop evidence" in text
    assert document.pages[0].geometry.rotation_degrees == 90


def test_canonicalize_fails_closed_without_pages() -> None:
    with pytest.raises(CanonicalizationError):
        canonicalize_parse_result(
            parse_result={"status": "succeeded", "pages": []},
            source_artifact_digest="a" * 64,
            candidate=_CANDIDATE,
            source_output_artifact_digest="b" * 64,
        )
