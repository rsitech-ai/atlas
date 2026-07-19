"""Deterministic approximate tokenizer and element flattening.

ponytail: whitespace/punct split approximates tokens; swap for a pinned
tokenizer only after dependency governance + frozen size recalibration.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass

from rsi_atlas_contracts import (
    CanonicalDocument,
    CanonicalElement,
)

_TOKEN_RE = re.compile(r"\S+")
_SENTENCE_RE = re.compile(r"(?<=[.!?])\s+")

# Development defaults under an explicit configuration hash (not production policy).
CHILD_TOKEN_TARGET = 400
CHILD_TOKEN_MIN = 250
CHILD_TOKEN_MAX = 450
PARENT_TOKEN_MIN = 900
PARENT_TOKEN_MAX = 1800
CHUNK_CONFIGURATION_HASH = hashlib.sha256(
    b"phase-2c-chunk-dev-1|child=400|parent=900-1800|approx-tokenizer"
).hexdigest()


@dataclass(frozen=True)
class FlatElement:
    element_id: str
    page_number: int
    reading_order: int
    kind: str
    role: str | None
    text: str
    row_count: int | None = None
    column_count: int | None = None


def approximate_token_count(text: str) -> int:
    tokens = _TOKEN_RE.findall(text)
    return max(1, len(tokens)) if text.strip() else 0


def split_sentences(text: str) -> tuple[str, ...]:
    parts = [part.strip() for part in _SENTENCE_RE.split(text) if part.strip()]
    return tuple(parts) if parts else ((text.strip(),) if text.strip() else ())


def flatten_elements(document: CanonicalDocument) -> tuple[FlatElement, ...]:
    flattened: list[FlatElement] = []
    for page in document.pages:
        for element in page.elements:
            flattened.append(_flat_element(element))
    return tuple(flattened)


def _flat_element(element: CanonicalElement) -> FlatElement:
    role: str | None = None
    row_count: int | None = None
    column_count: int | None = None
    if element.kind == "text":
        role = element.role.value
    elif element.kind == "table":
        row_count = element.row_count
        column_count = element.column_count
    return FlatElement(
        element_id=element.element_id,
        page_number=element.page_number,
        reading_order=element.reading_order,
        kind=element.kind,
        role=role,
        text=element.normalized_text,
        row_count=row_count,
        column_count=column_count,
    )


def join_texts(parts: list[str]) -> str:
    return "\n".join(part for part in parts if part)


def sorted_pages(page_numbers: set[int] | list[int] | tuple[int, ...]) -> tuple[int, ...]:
    return tuple(sorted(set(page_numbers)))
