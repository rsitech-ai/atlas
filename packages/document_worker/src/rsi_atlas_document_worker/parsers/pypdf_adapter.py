"""Bounded pypdf text-span candidate adapter."""

from __future__ import annotations

import os
from typing import Any

from pypdf import PdfReader
from pypdf.errors import PdfReadError


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
            pages.append(
                {
                    "page_number": index,
                    "width": mediabox[2] - mediabox[0],
                    "height": mediabox[3] - mediabox[1],
                    "spans": [
                        {
                            "text": text,
                            "source_box": {
                                "left": mediabox[0],
                                "bottom": mediabox[1],
                                "right": mediabox[2],
                                "top": mediabox[3],
                            },
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
