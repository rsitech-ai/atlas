from __future__ import annotations

import os
from pathlib import Path

from rsi_atlas_document_worker.parsers import (
    DoclingParserCandidate,
    PdfMinerParserCandidate,
    PyPdfParserCandidate,
)

FIXTURE = Path("packages/ingestion/benchmarks/pdf/fixtures/crypto_technical_three_page.pdf")


def test_pypdf_candidate_returns_pages_and_spans() -> None:
    fd = os.open(FIXTURE, os.O_RDONLY)
    try:
        result = PyPdfParserCandidate().parse(artifact_fd=fd)
    finally:
        os.close(fd)
    assert result["status"] == "succeeded"
    assert len(result["pages"]) == 3
    assert any(page["spans"] for page in result["pages"])


def test_pdfminer_candidate_returns_ordered_spans() -> None:
    fd = os.open(FIXTURE, os.O_RDONLY)
    try:
        result = PdfMinerParserCandidate().parse(artifact_fd=fd)
    finally:
        os.close(fd)
    assert result["status"] == "succeeded"
    assert len(result["pages"]) == 3
    assert any(page["spans"] for page in result["pages"])


def test_docling_candidate_stays_blocked() -> None:
    result = DoclingParserCandidate().parse(artifact_fd=3)
    assert result["status"] == "blocked"
    assert result["reason"] == "blocked_dependency_governance"
