# RSI Atlas

RSI Atlas is a local-first crypto intelligence and research operating system for evidence-backed, reproducible analysis on Apple Silicon Macs.

The approved product and system design is in [`docs/superpowers/specs/2026-07-18-rsi-atlas-design.md`](docs/superpowers/specs/2026-07-18-rsi-atlas-design.md). The first implementation plan is in [`docs/superpowers/plans/2026-07-18-foundation-runtime-status.md`](docs/superpowers/plans/2026-07-18-foundation-runtime-status.md).

## Current slice

The repository currently implements the durable foundation of the first Phase 1 seam:

- strict, versioned Python runtime-status contracts;
- an immutable, content-addressed artifact store with integrity verification;
- PostgreSQL 17 persistence with data checksums over an owner-only Unix socket and hash-locked migrations;
- a pgvector-enabled foundation schema with tenant/workspace authorization and actor/trace provenance;
- deterministic offline foundation diagnostics;
- `atlas doctor` and `GET /v1/system/status` on loopback only;
- a native SwiftUI Command Center with loading, healthy, unavailable, and retry states;
- a reproducible SwiftPM `.app` build and local engine/app launcher.

Document ingestion, retrieval, local models, collectors, LangGraph workflows, XPC, signing, and release qualification are not implemented yet. The development database is project-owned; release data placement remains a later packaging gate.

## Requirements

- Apple Silicon Mac running macOS 15 or newer
- Xcode command-line tools with Swift 6
- Python 3.11 or newer
- [uv](https://docs.astral.sh/uv/)
- Homebrew PostgreSQL 17.10 and pgvector 0.8.5

## Run

```bash
./script/build_and_run.sh --verify
```

This syncs the pinned Python workspace, starts the project-owned PostgreSQL cluster under `.local` on an owner-only Unix socket, starts the engine on `127.0.0.1:8765`, builds `RSIAtlas`, stages `dist/RSIAtlas.app`, launches it, and verifies both app processes.

The local database never uses the Homebrew service or its default cluster:

```bash
./infra/local/postgres.sh start
./infra/local/postgres.sh status
./infra/local/postgres.sh stop
```

Override `RSI_ATLAS_DATA_ROOT` to place the development cluster outside the repository. The PostgreSQL root, data directory, and socket directory are restricted to the current user.

## Verify

```bash
uv lock --check
uv run ruff check packages services
uv run mypy packages/contracts/src packages/storage/src services/engine/src
RSI_ATLAS_TEST_DATABASE_URL="$(./infra/local/postgres.sh test-url)" uv run pytest -q
uv run atlas doctor --json
swift test --package-path apps/macos
swift build --package-path apps/macos --product RSIAtlas
```

The product is research-only. It has no trading, wallet, signing, custody, or private-key authority.
