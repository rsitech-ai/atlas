"""Fail-closed system Tesseract OCR (no model download)."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path


class OcrUnavailable(RuntimeError):
    """Raised when Tesseract is missing or fails."""


def tesseract_binary() -> str | None:
    return shutil.which("tesseract")


def require_tesseract() -> str:
    binary = tesseract_binary()
    if binary is None:
        raise OcrUnavailable("blocked_ocr_unavailable: tesseract not on PATH")
    return binary


def ocr_image_to_text(image_path: Path, *, lang: str = "eng") -> str:
    """Run system tesseract on a local image. Fail closed if unavailable."""
    binary = require_tesseract()
    if not image_path.is_file():
        raise OcrUnavailable(f"ocr image missing: {image_path}")
    try:
        completed = subprocess.run(
            [binary, str(image_path), "stdout", "-l", lang],
            check=False,
            capture_output=True,
            text=True,
            timeout=60,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise OcrUnavailable(f"blocked_ocr_unavailable: {error}") from error
    if completed.returncode != 0:
        raise OcrUnavailable(f"blocked_ocr_unavailable: tesseract exit {completed.returncode}")
    return completed.stdout


__all__ = [
    "OcrUnavailable",
    "ocr_image_to_text",
    "require_tesseract",
    "tesseract_binary",
]
