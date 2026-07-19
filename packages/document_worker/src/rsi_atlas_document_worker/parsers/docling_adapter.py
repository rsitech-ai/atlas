"""Docling remains evaluation-blocked until dependency governance clears."""

from __future__ import annotations

from typing import Any


class DoclingParserCandidate:
    name = "docling"
    version = "2.113.0"
    tier = 1

    def parse(self, *, artifact_fd: int, max_pages: int = 2000) -> dict[str, Any]:
        del artifact_fd, max_pages
        return {
            "status": "blocked",
            "reason": "blocked_dependency_governance",
            "pages": [],
            "warnings": ["docling_not_installed"],
            "unsupported_evidence": ["all"],
        }
