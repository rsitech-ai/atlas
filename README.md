# RSI Atlas

RSI Atlas is a local-first crypto intelligence and research operating system for evidence-backed, reproducible analysis on Apple Silicon Macs.

The approved product and system design is in [`docs/superpowers/specs/2026-07-18-rsi-atlas-design.md`](docs/superpowers/specs/2026-07-18-rsi-atlas-design.md). The first implementation plan is in [`docs/superpowers/plans/2026-07-18-foundation-runtime-status.md`](docs/superpowers/plans/2026-07-18-foundation-runtime-status.md).

## Current slice

The repository currently implements the first Phase 1 seam:

- strict, versioned Python runtime-status contracts;
- deterministic offline foundation diagnostics;
- `atlas doctor` and `GET /v1/system/status` on loopback only;
- a native SwiftUI Command Center with loading, healthy, unavailable, and retry states;
- a reproducible SwiftPM `.app` build and local engine/app launcher.

PostgreSQL, artifact storage, document ingestion, retrieval, local models, collectors, LangGraph workflows, XPC, signing, and release qualification are not implemented yet.

## Requirements

- Apple Silicon Mac running macOS 15 or newer
- Xcode command-line tools with Swift 6
- Python 3.11 or newer
- [uv](https://docs.astral.sh/uv/)

## Run

```bash
./script/build_and_run.sh --verify
```

This syncs the pinned Python workspace, starts the engine on `127.0.0.1:8765`, builds `RSIAtlas`, stages `dist/RSIAtlas.app`, launches it, and verifies both processes.

## Verify

```bash
uv lock --check
uv run ruff check packages services
uv run mypy packages/contracts/src services/engine/src
uv run pytest -q
uv run atlas doctor --json
swift test --package-path apps/macos
swift build --package-path apps/macos --product RSIAtlas
```

The product is research-only. It has no trading, wallet, signing, custody, or private-key authority.
