"""Bounded pypdf text-span candidate adapter."""

from __future__ import annotations

import os
from typing import Any

from pypdf import PdfReader
from pypdf.errors import PdfReadError


def _box(values: list[float]) -> dict[str, float]:
    return {
        "left": float(values[0]),
        "bottom": float(values[1]),
        "right": float(values[2]),
        "top": float(values[3]),
    }


class PyPdfParserCandidate:
    name = "pypdf"
    version = "6.14.2"
    tier = 0

    def parse(self, *, artifact_fd: int, max_pages: int = 2000) -> dict[str, Any]:
        try:
            reader = PdfReader(os.fdopen(os.dup(artifact_fd), "rb"), strict=True)
        except (OSError, PdfReadError, ValueError) as error:
            return {
                "status": "failed",
                "reason": "unreadable_pdf",
                "pages": [],
                "warnings": [type(error).__name__],
            }
        if getattr(reader, "is_encrypted", False):
            return {
                "status": "failed",
                "reason": "encrypted",
                "pages": [],
                "warnings": ["password_required_or_encrypted"],
            }
        pages: list[dict[str, Any]] = []
        warnings: list[str] = []
        for index, page in enumerate(reader.pages, start=1):
            if index > max_pages:
                warnings.append("page_limit_reached")
                break
            try:
                text = page.extract_text() or ""
            except Exception:
                text = ""
                warnings.append(f"page_{index}_extract_failed")
            mediabox = [float(value) for value in page.mediabox]
            cropbox = [float(value) for value in (page.cropbox or page.mediabox)]
            rotation = int(page.get("/Rotate", 0) or 0) % 360
            if rotation not in {0, 90, 180, 270}:
                warnings.append(f"page_{index}_unsupported_rotation")
                rotation = 0
            pages.append(
                {
                    "page_number": index,
                    "width": mediabox[2] - mediabox[0],
                    "height": mediabox[3] - mediabox[1],
                    "media_box": _box(mediabox),
                    "crop_box": _box(cropbox),
                    "rotation_degrees": rotation,
                    "spans": [
                        {
                            "text": text,
                            "source_box": _box(cropbox),
                        }
                    ]
                    if text
                    else [],
                }
            )
        return {
            "status": "succeeded",
            "reason": None,
            "pages": pages,
            "warnings": sorted(set(warnings)),
            "unsupported_evidence": ["fonts", "links", "images"],
        }
