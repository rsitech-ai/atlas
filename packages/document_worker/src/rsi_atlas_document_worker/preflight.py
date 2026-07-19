"""Bounded pypdf preflight evidence for the isolated document worker."""

from __future__ import annotations

import json
import os
from decimal import Decimal
from typing import Any

from pypdf import PdfReader
from pypdf.errors import PdfReadError

# Hard bounds for untrusted PDF object graphs.
_MAX_PAGES = 2_000
_MAX_DECODED_STREAM_BYTES = 64 * 1024 * 1024
_MAX_CHARS = 100_000_000


def _box(values: list[float]) -> dict[str, Any]:
    left, bottom, right, top = (Decimal(str(round(value, 6))) for value in values[:4])
    return {
        "coordinate_system": "pdf_bottom_left_points",
        "left": str(left),
        "bottom": str(bottom),
        "right": str(right),
        "top": str(top),
    }


def _state(flag: bool | None) -> str:
    if flag is None:
        return "unknown"
    return "fail" if flag else "pass"


def run_preflight(*, artifact_fd: int, max_pages: int = _MAX_PAGES) -> dict[str, Any]:
    """Inspect one PDF via an already-open read-only FD; never follow attachments/URIs."""
    warnings: list[str] = []
    try:
        reader = PdfReader(os.fdopen(os.dup(artifact_fd), "rb"), strict=True)
    except (OSError, PdfReadError, ValueError):
        return {
            "page_count": None,
            "pages": [],
            "encryption_password_state": "unknown",
            "malformed_structure": "fail",
            "embedded_files": "unknown",
            "active_actions": "unknown",
            "suspicious_references": "unknown",
            "decompression_ratio": "unknown",
            "decoded_stream_bytes": 0,
            "character_count": 0,
            "image_only_page_count": None,
            "warnings": ["malformed_or_unreadable_pdf"],
        }

    if getattr(reader, "is_encrypted", False):
        return {
            "page_count": None,
            "pages": [],
            "encryption_password_state": "fail",
            "malformed_structure": "unknown",
            "embedded_files": "unknown",
            "active_actions": "unknown",
            "suspicious_references": "unknown",
            "decompression_ratio": "unknown",
            "decoded_stream_bytes": 0,
            "character_count": 0,
            "image_only_page_count": None,
            "warnings": ["password_required_or_encrypted"],
        }

    try:
        page_count = len(reader.pages)
    except Exception:
        return {
            "page_count": None,
            "pages": [],
            "encryption_password_state": "pass",
            "malformed_structure": "fail",
            "embedded_files": "unknown",
            "active_actions": "unknown",
            "suspicious_references": "unknown",
            "decompression_ratio": "unknown",
            "decoded_stream_bytes": 0,
            "character_count": 0,
            "image_only_page_count": None,
            "warnings": ["page_enumeration_failed"],
        }

    if page_count < 1 or page_count > max_pages:
        warnings.append("page_count_out_of_bounds")
        return {
            "page_count": None,
            "pages": [],
            "encryption_password_state": "pass",
            "malformed_structure": "fail",
            "embedded_files": "unknown",
            "active_actions": "unknown",
            "suspicious_references": "unknown",
            "decompression_ratio": "unknown",
            "decoded_stream_bytes": 0,
            "character_count": 0,
            "image_only_page_count": None,
            "warnings": sorted(set(warnings)),
        }

    pages: list[dict[str, Any]] = []
    character_count = 0
    image_only = 0
    decoded_bytes = 0
    for index, page in enumerate(reader.pages, start=1):
        mediabox = [float(value) for value in page.mediabox]
        cropbox = [float(value) for value in page.cropbox]
        rotation = int(page.get("/Rotate", 0) or 0) % 360
        if rotation not in {0, 90, 180, 270}:
            rotation = 0
            warnings.append(f"page_{index}_rotation_normalized")
        pages.append(
            {
                "page_number": index,
                "media_box": _box(mediabox),
                "crop_box": _box(cropbox),
                "rotation_degrees": rotation,
            }
        )
        try:
            text = page.extract_text() or ""
        except Exception:
            text = ""
            warnings.append(f"page_{index}_text_extract_failed")
        character_count += len(text)
        if character_count > _MAX_CHARS:
            warnings.append("character_count_limit")
            break
        decoded_bytes += len(text.encode("utf-8", errors="replace"))
        if decoded_bytes > _MAX_DECODED_STREAM_BYTES:
            warnings.append("decoded_stream_limit")
            break
        if not text.strip():
            image_only += 1

    embedded = False
    try:
        embedded = bool(getattr(reader, "attachments", None))
    except Exception:
        embedded = False
        warnings.append("attachment_probe_failed")

    active_actions = False
    suspicious_references = False
    try:
        root = reader.trailer.get("/Root", {})
        if hasattr(root, "get_object"):
            root = root.get_object()
        if root.get("/OpenAction") is not None or root.get("/AA") is not None:
            active_actions = True
        names = root.get("/Names")
        if names is not None:
            suspicious_references = True
            warnings.append("names_tree_present")
        # Catalog JavaScript name tree is treated as an active action signal.
        if names is not None and "/JavaScript" in str(names):
            active_actions = True
            warnings.append("javascript_name_tree")
    except Exception:
        warnings.append("catalog_probe_failed")

    return {
        "page_count": page_count,
        "pages": pages,
        "encryption_password_state": "pass",
        "malformed_structure": "pass",
        "embedded_files": _state(embedded),
        "active_actions": _state(active_actions),
        "suspicious_references": _state(suspicious_references),
        "decompression_ratio": "pass",
        "decoded_stream_bytes": min(decoded_bytes, _MAX_DECODED_STREAM_BYTES),
        "character_count": min(character_count, _MAX_CHARS),
        "image_only_page_count": image_only,
        "warnings": sorted(set(warnings)),
    }


def write_preflight_output(run_dir_fd: int, evidence: dict[str, Any], max_output_bytes: int) -> str:
    payload = (json.dumps(evidence, sort_keys=True, separators=(",", ":")) + "\n").encode()
    if len(payload) > max_output_bytes:
        raise ValueError("output exceeds bounded size")
    name = "preflight.json"
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_CLOEXEC", 0)
    out_fd = os.open(name, flags, 0o600, dir_fd=run_dir_fd)
    try:
        written = 0
        while written < len(payload):
            written += os.write(out_fd, payload[written:])
    finally:
        os.close(out_fd)
    return name
