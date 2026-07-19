from __future__ import annotations

from rsi_atlas_document_worker.parsers import (
    DoclingParserCandidate,
    PdfMinerParserCandidate,
    PyPdfParserCandidate,
)
from rsi_atlas_ingestion.parser_benchmark import qualify_development_candidate, score_candidate


def test_pypdf_passes_born_digital_accept_fixtures() -> None:
    scores = score_candidate(PyPdfParserCandidate())
    accept = [score for score in scores if score.route == "accept"]
    assert accept
    assert all(score.status == "passed" for score in accept)
    assert all(score.page_coverage == 1.0 for score in accept)
    assert all(score.string_coverage == 1.0 for score in accept)


def test_pdfminer_fails_rotated_crop_string_coverage() -> None:
    scores = score_candidate(PdfMinerParserCandidate())
    rotated = next(score for score in scores if score.fixture == "rotated_crop_box.pdf")
    assert rotated.status == "failed"
    assert rotated.string_coverage < 1.0


def test_docling_remains_blocked_in_benchmark() -> None:
    scores = score_candidate(DoclingParserCandidate())
    assert scores
    assert all(score.status == "blocked" for score in scores)


def test_qualification_record_selects_tier0_pypdf() -> None:
    record = qualify_development_candidate(force=True)
    qualified = record["qualified_development_candidate"]
    assert qualified is not None
    assert qualified["candidate"] == "pypdf"
    assert qualified["production_promoted"] is False
    assert record["docling"]["status"] == "blocked_dependency_governance"
