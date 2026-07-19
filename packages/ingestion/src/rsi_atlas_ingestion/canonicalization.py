"""Pure Tier-0 PDF parse → canonical page transform (no I/O)."""

from __future__ import annotations

import hashlib
import unicodedata
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Any
from uuid import UUID

from rsi_atlas_contracts import (
    BoundingBox,
    CanonicalDocument,
    CanonicalPage,
    CanonicalTextElement,
    CanonicalTextRole,
    CoordinateSystem,
    PageGeometry,
    ParserCandidateIdentity,
    ParserQualityDecision,
    ParserQualityReport,
    build_canonical_document,
    canonical_element_identifier,
    canonicalization_identifier,
    parser_span_source_hash,
    sha256_text,
)

NORMALIZER_VERSION = "nfc-1"
NORMALIZER_CONFIGURATION_HASH = hashlib.sha256(b"phase-2b-normalizer-nfc-1").hexdigest()
_COORD_Q = Decimal("0.000001")


class CanonicalizationError(ValueError):
    """Raised when candidate evidence cannot be canonicalized fail-closed."""


def _fixed(value: float | Decimal | str) -> Decimal:
    try:
        quantized = Decimal(str(value)).quantize(_COORD_Q)
    except (InvalidOperation, ValueError) as error:
        raise CanonicalizationError("non_finite_or_invalid_coordinate") from error
    if not quantized.is_finite():
        raise CanonicalizationError("non_finite_or_invalid_coordinate")
    if quantized.is_zero():
        return Decimal("0.000000")
    return quantized


def _pdf_box(payload: dict[str, Any]) -> BoundingBox:
    return BoundingBox(
        coordinate_system=CoordinateSystem.PDF_BOTTOM_LEFT_POINTS,
        left=_fixed(payload["left"]),
        bottom=_fixed(payload["bottom"]),
        right=_fixed(payload["right"]),
        top=_fixed(payload["top"]),
    )


def normalize_text(raw: str) -> str:
    """NFC normalize without inventing or repairing content beyond Unicode form."""
    return unicodedata.normalize("NFC", raw)


def pdf_box_to_normalized(
    raw: BoundingBox,
    *,
    crop: BoundingBox,
    rotation_degrees: int,
) -> BoundingBox:
    """Convert a PDF-space box into normalized top-left coordinates inside crop."""
    if raw.coordinate_system is not CoordinateSystem.PDF_BOTTOM_LEFT_POINTS:
        raise CanonicalizationError("raw_box_coordinate_system")
    width = crop.right - crop.left
    height = crop.top - crop.bottom
    if width <= 0 or height <= 0:
        raise CanonicalizationError("invalid_crop_geometry")

    left = (raw.left - crop.left) / width
    right = (raw.right - crop.left) / width
    bottom = (raw.bottom - crop.bottom) / height
    top = (raw.top - crop.bottom) / height

    if rotation_degrees == 0:
        norm_left, norm_top, norm_right, norm_bottom = left, 1 - top, right, 1 - bottom
    elif rotation_degrees == 90:
        norm_left, norm_top, norm_right, norm_bottom = bottom, left, top, right
    elif rotation_degrees == 180:
        norm_left, norm_top, norm_right, norm_bottom = 1 - right, top, 1 - left, bottom
    elif rotation_degrees == 270:
        norm_left, norm_top, norm_right, norm_bottom = 1 - top, 1 - right, 1 - bottom, 1 - left
    else:
        raise CanonicalizationError("unsupported_rotation")

    return BoundingBox(
        coordinate_system=CoordinateSystem.NORMALIZED_TOP_LEFT,
        left=_fixed(min(norm_left, norm_right)),
        top=_fixed(min(norm_top, norm_bottom)),
        right=_fixed(max(norm_left, norm_right)),
        bottom=_fixed(max(norm_top, norm_bottom)),
    )


def _page_geometry(page: dict[str, Any]) -> PageGeometry:
    media = page.get("media_box") or {
        "left": 0.0,
        "bottom": 0.0,
        "right": float(page["width"]),
        "top": float(page["height"]),
    }
    crop = page.get("crop_box") or media
    rotation = int(page.get("rotation_degrees") or 0)
    if rotation not in {0, 90, 180, 270}:
        raise CanonicalizationError("unsupported_rotation")
    return PageGeometry(
        page_number=int(page["page_number"]),
        media_box=_pdf_box(media),
        crop_box=_pdf_box(crop),
        rotation_degrees=rotation,  # type: ignore[arg-type]
    )


def canonicalize_parse_result(
    *,
    parse_result: dict[str, Any],
    source_artifact_digest: str,
    candidate: ParserCandidateIdentity,
    source_output_artifact_digest: str,
) -> tuple[CanonicalDocument, list[str]]:
    """Transform Tier-0 candidate pages into a CanonicalDocument."""
    warning_codes = {
        code
        for code in (parse_result.get("warnings") or [])
        if isinstance(code, str)
        and code
        and code == code.casefold()
        and all(character in "abcdefghijklmnopqrstuvwxyz0123456789_" for character in code)
    }
    if parse_result.get("status") != "succeeded":
        raise CanonicalizationError("parse_result_not_succeeded")
    pages_in = parse_result.get("pages") or []
    if not pages_in:
        raise CanonicalizationError("no_pages")

    canonicalization_id = canonicalization_identifier(
        artifact_digest=source_artifact_digest,
        parser_build_hash=candidate.build_hash,
        parser_configuration_hash=candidate.configuration_hash,
        normalizer_version=NORMALIZER_VERSION,
        normalizer_configuration_hash=NORMALIZER_CONFIGURATION_HASH,
    )

    pages: list[CanonicalPage] = []
    for page in pages_in:
        geometry = _page_geometry(page)
        elements: list[CanonicalTextElement] = []
        for order, span in enumerate(page.get("spans") or []):
            raw_text = span.get("text") or ""
            if not raw_text.strip():
                continue
            try:
                raw_box = _pdf_box(span["source_box"])
                norm_box = pdf_box_to_normalized(
                    raw_box,
                    crop=geometry.crop_box,
                    rotation_degrees=geometry.rotation_degrees,
                )
            except (CanonicalizationError, KeyError, TypeError, ValueError) as error:
                raise CanonicalizationError("invalid_source_box") from error
            normalized = normalize_text(raw_text)
            raw_hash = sha256_text(raw_text)
            span_id = f"span_{order:04d}"
            source_hash = parser_span_source_hash(
                source_output_artifact_digest=source_output_artifact_digest,
                candidate=candidate,
                span_id=span_id,
                page_number=geometry.page_number,
                reading_order=order,
                raw_bounding_box=raw_box,
                raw_text_hash=raw_hash,
            )
            role = (
                CanonicalTextRole.HEADING
                if order == 0 and len(normalized) < 120
                else CanonicalTextRole.PARAGRAPH
            )
            elements.append(
                CanonicalTextElement(
                    kind="text",
                    role=role,
                    canonicalization_id=canonicalization_id,
                    element_id=canonical_element_identifier(
                        canonicalization_id=canonicalization_id,
                        page_number=geometry.page_number,
                        kind="text",
                        reading_order=order,
                        bounding_box=norm_box,
                        raw_text_hash=raw_hash,
                    ),
                    page_number=geometry.page_number,
                    reading_order=order,
                    bounding_box=norm_box,
                    raw_bounding_box=raw_box,
                    raw_text=raw_text,
                    raw_text_hash=raw_hash,
                    normalized_text=normalized,
                    normalized_text_hash=sha256_text(normalized),
                    parent_section_id=None,
                    parser_confidence=1.0,
                    ocr_confidence=None,
                    language="unknown",
                    source_output_artifact_digest=source_output_artifact_digest,
                    source_span_id=span_id,
                    source_span_hash=source_hash,
                    source_hash=source_hash,
                )
            )
        if not elements:
            raise CanonicalizationError("empty_page_elements")
        pages.append(
            CanonicalPage(
                canonicalization_id=canonicalization_id,
                source_artifact_digest=source_artifact_digest,
                page_number=geometry.page_number,
                geometry=geometry,
                elements=tuple(elements),
            )
        )

    document = build_canonical_document(
        source_artifact_digest=source_artifact_digest,
        candidate=candidate,
        normalizer_version=NORMALIZER_VERSION,
        normalizer_configuration_hash=NORMALIZER_CONFIGURATION_HASH,
        pages=tuple(pages),
    )
    return document, sorted(warning_codes)


def build_quality_report(
    *,
    parser_run_id: UUID,
    candidate: ParserCandidateIdentity,
    document: CanonicalDocument,
    parse_result: dict[str, Any],
    deterministic_output_hash: str,
    evaluated_at: datetime,
    warnings: list[str],
) -> ParserQualityReport:
    page_count = len(document.pages)
    pages_with_content = sum(1 for page in document.pages if page.elements)
    text = "\n".join(
        element.normalized_text for page in document.pages for element in page.elements
    )
    replacement_rate = (text.count("\ufffd") / len(text)) if text else 0.0
    coverage = pages_with_content / page_count if page_count else 0.0
    decision = (
        ParserQualityDecision.QUALIFIED
        if (
            parse_result.get("status") == "succeeded"
            and coverage == 1.0
            and pages_with_content > 0
            and replacement_rate <= 0.01
        )
        else ParserQualityDecision.REVIEW_REQUIRED
    )
    return ParserQualityReport(
        parser_run_id=parser_run_id,
        candidate=candidate,
        page_count=page_count,
        pages_with_content=pages_with_content,
        page_coverage=coverage,
        replacement_character_rate=replacement_rate,
        crypto_token_preservation_rate=1.0,
        valid_bounding_box_rate=1.0,
        deterministic_output_hash=deterministic_output_hash,
        decision=decision,
        warnings=tuple(sorted(set(warnings))),
        evaluated_at=evaluated_at,
    )
