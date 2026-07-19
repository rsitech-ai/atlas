"""Bounded pdfminer.six layout-span candidate adapter."""

from __future__ import annotations

import os
from typing import Any

from pdfminer.high_level import extract_pages
from pdfminer.layout import LTTextContainer, LTTextLine


class PdfMinerParserCandidate:
    name = "pdfminer.six"
    version = "20260107"
    tier = 0

    def parse(self, *, artifact_fd: int, max_pages: int = 2000) -> dict[str, Any]:
        warnings: list[str] = []
        pages: list[dict[str, Any]] = []
        try:
            with os.fdopen(os.dup(artifact_fd), "rb") as handle:
                for index, page_layout in enumerate(extract_pages(handle), start=1):
                    if index > max_pages:
                        warnings.append("page_limit_reached")
                        break
                    spans: list[dict[str, Any]] = []
                    for element in page_layout:
                        if not isinstance(element, LTTextContainer):
                            continue
                        for line in element:
                            if not isinstance(line, LTTextLine):
                                continue
                            text = line.get_text()
                            if not text.strip():
                                continue
                            x0, y0, x1, y1 = line.bbox
                            spans.append(
                                {
                                    "text": text,
                                    "source_box": {
                                        "left": float(x0),
                                        "bottom": float(y0),
                                        "right": float(x1),
                                        "top": float(y1),
                                    },
                                }
                            )
                    pages.append(
                        {
                            "page_number": index,
                            "width": float(page_layout.width),
                            "height": float(page_layout.height),
                            "spans": spans,
                        }
                    )
        except Exception as error:
            return {
                "status": "failed",
                "reason": "unreadable_pdf",
                "pages": [],
                "warnings": [type(error).__name__],
            }
        return {
            "status": "succeeded",
            "reason": None,
            "pages": pages,
            "warnings": sorted(set(warnings)),
            "unsupported_evidence": ["links"],
        }
