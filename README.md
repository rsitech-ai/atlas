# RSI Atlas

Local-first **crypto intelligence and research** OS for evidence-backed, reproducible analysis on **Apple Silicon** Macs.

RSI Atlas is maintained by [RSI Tech](https://rsitech.ai). Public project questions and private
security or confidentiality-sensitive reports can be sent to
[info@rsitech.ai](mailto:info@rsitech.ai).

| Status | Detail |
| --- | --- |
| Maturity | **Dev-complete / not production Proven** — phases 1–6 implemented with tests; standalone packaging, signed-artifact verification, notarization, sealed embedding promotion, and related proofs remain open |
| Platform | macOS 15+, Apple Silicon, Swift 6, Python 3.11+ |
| License | [Apache-2.0](LICENSE) — see [NOTICE](NOTICE) for third-party notes |
| Maintainer | [RSI Tech](https://rsitech.ai) |
| Contact | [info@rsitech.ai](mailto:info@rsitech.ai) |
| Trading / custody | **None** — research only; no wallet, signing, or private-key authority |

Design: [`docs/superpowers/specs/2026-07-18-rsi-atlas-design.md`](docs/superpowers/specs/2026-07-18-rsi-atlas-design.md).  
Acceptance honesty: [`docs/acceptance-matrix.md`](docs/acceptance-matrix.md).

## What you get

- Versioned Python runtime contracts, content-addressed artifact store, PostgreSQL 17 + pgvector over an **owner-only Unix socket**
- Fail-closed document admission (quarantine / reject / duplicate-link; never silent promote)
- Governed Tier-0 PDF parse (`pypdf` / `pdfminer.six`); **Docling blocked**
- Chunking, hybrid retrieval, cited report drafts, offline collectors, monitoring, backup/restore, SBOM / unsigned release checks
- Native SwiftUI Command Center + Evidence / Research / Comparison surfaces bound to loopback (or release Unix IPC) APIs

## What is still blocked or candidate-only

- Standalone release assembly and **Developer ID signing / notarization / stapling**. A usable
  Developer ID identity is installed locally, but no self-contained signed artifact or notary
  credential evidence exists; see `docs/release/signing-notarization-blockers.md`.
- Docling; system Tesseract OCR when absent (fail-closed)
- Sealed-holdout **PRODUCTION** embedding promotion, neural cross-encoder, calibrated semantic triage
- Keychain-wrapped backup keys; WebSocket collectors; LangGraph; XPC
- Parent-child / table-aware chunkers remain development-qualified

## Requirements

- Apple Silicon Mac, macOS 15+
- Xcode command-line tools (Swift 6)
- Python 3.11+ and [uv](https://docs.astral.sh/uv/)
- Homebrew PostgreSQL **17.10** and pgvector **0.8.5**

## Quick start

```bash
uv sync
./infra/local/postgres.sh start
./script/build_and_run.sh --verify
```

This syncs the workspace, starts the **project-owned** Postgres cluster under `.local` (not the Homebrew service), launches the engine on `127.0.0.1:8765`, stages `dist/RSIAtlas.app`, and checks the degraded-only-model component contract.

Unix-domain IPC instead of loopback TCP:

```bash
./script/build_and_run.sh --release-ipc
```

Override data root without hard-coding a personal home path:

```bash
export RSI_ATLAS_DATA_ROOT="$HOME/Library/Application Support/RSIAtlas-dev"
./infra/local/postgres.sh start
```

## Verify

```bash
uv lock --check
uv run ruff check packages services infra
uv run ruff format --check packages services infra
uv run mypy packages services infra
RSI_ATLAS_TEST_DATABASE_URL="$(./infra/local/postgres.sh test-url)" uv run pytest -q
uv run atlas doctor --json
swift test --package-path apps/macos
swift build --package-path apps/macos --product RSIAtlas
```

CI runs lint/typecheck and a DB-free unit subset; full Postgres integration needs the local Unix-socket URL above (TCP hosts are rejected by policy).

## Optional OSS embeddings

Default tests use fixture vectors. For the governed offline candidate:

```bash
uv sync --package rsi-atlas-ingestion --extra onnx
uv run python script/install_embedding_model.py --download
export RSI_ATLAS_EMBEDDER=onnx
export RSI_ATLAS_EMBEDDING_ARTIFACT_DIR="/path/to/artifact-dir"
```

Without that, prefer `oss_token_hash_v1` for production-local dense. Neither path is sealed PRODUCTION without promotion evidence.

## Architecture pointers

| Topic | Doc |
| --- | --- |
| System design | `docs/superpowers/specs/2026-07-18-rsi-atlas-design.md` |
| Dependency governance | `docs/dependency-governance/` |
| Signing blockers | `docs/release/signing-notarization-blockers.md` |
| Production plan | `docs/production-plan.md` |

## Contributing / security

- [CONTRIBUTING.md](CONTRIBUTING.md) — build, test, PR norms
- [SECURITY.md](SECURITY.md) — private vulnerability reporting
- [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md)

## Disclaimer

Research software. Outputs are not financial advice. Operators are responsible for local data, network allowlists, and any Apple signing credentials they supply outside this repository.
