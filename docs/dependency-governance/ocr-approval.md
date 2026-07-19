# OCR dependency approval

Status: **approved** (system Tesseract only; fail-closed if absent)

## Decision

Approved on 2026-07-19 by actor `andrzej:oss-production-ready-instruction`.

Docling remains **blocked**. OCR may use system-installed Tesseract (Apache-2.0) via an
explicit subprocess boundary when the binary is present. No PyPI OCR model packs, no VLM,
no silent downloads.

### Allowed

- `tesseract` CLI on `PATH` (Homebrew `tesseract`) for scanned-page fallback assessment
- Fail-closed `blocked_ocr_unavailable` when binary missing or non-zero exit

### Not allowed

- Docling / EasyOCR / Paddle / cloud OCR
- Bundling traineddata downloads inside application startup
- Claiming production OCR criterion closure without sealed scanned holdout

### Rollback

Remove OCR adapter; scanned paths stay preflight-rejected / quarantined as today.
