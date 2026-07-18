# RSI Atlas

RSI Atlas is a local-first crypto intelligence and research operating system for evidence-backed, reproducible analysis on Apple Silicon Macs.

The approved product and system design is in [`docs/superpowers/specs/2026-07-18-rsi-atlas-design.md`](docs/superpowers/specs/2026-07-18-rsi-atlas-design.md). The first implementation plan is in [`docs/superpowers/plans/2026-07-18-foundation-runtime-status.md`](docs/superpowers/plans/2026-07-18-foundation-runtime-status.md).

## Current slice

The repository completes the reviewed Phase 1 durable local-runtime seam and Phase 2A secure
document-admission checkpoint:

- strict, versioned Python runtime-status contracts;
- an immutable, content-addressed artifact store with integrity verification;
- PostgreSQL 17 persistence with data checksums over an owner-only Unix socket and hash-locked migrations;
- a pgvector-enabled foundation schema with tenant/workspace authorization and actor/trace provenance;
- metadata-only owner-private local traces, enforced offline process policy, resource admission,
  and a model registry with an honest unavailable provider;
- real dependency-injected runtime diagnostics with exact component/group contracts and typed
  remediation;
- `atlas doctor` and `GET /v1/system/status` on loopback only;
- a native SwiftUI Command Center with grouped live evidence, stale-state preservation, fault
  remediation, multi-window behavior, keyboard refresh, and accessibility identifiers;
- strict cross-language acquisition, safety-profile, admission-decision, and durable-record
  contracts;
- bounded raw PDF streaming into owner-private staging and immutable content-addressed storage,
  followed by append-only PostgreSQL acquisition, decision, duplicate-link, and outbox evidence;
- a conservative admission policy that can quarantine, reject unsafe input, or link an exact
  same-workspace duplicate, but can never silently promote a document; the versioned contract can
  represent a password request once Phase 2B supplies authoritative encryption evidence;
- native and CLI import boundaries with stable acquisition/trace identity, idempotent retry,
  hard-kill orphan recovery, strict response binding, and no remote fallback;
- a native Evidence destination showing truthful empty, progress, review, rejected, duplicate,
  failure, and retry states with accessible identifiers; its password presentation is contract-tested
  but runtime-unreachable in Phase 2A, where encrypted markers remain unknown and quarantined;
- a reproducible SwiftPM `.app` build and local engine/app launcher.

Parser execution, OCR/scanned fallback, canonical page/layout provenance, chunking, indexes,
retrieval, qualified model execution, collectors, LangGraph workflows, XPC, signing, and release
qualification are not implemented yet. Every imported PDF therefore remains raw immutable evidence
with a fail-closed admission outcome; it is not parsed or searchable. The development database is
project-owned; release data placement remains a later packaging gate.

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

This syncs the pinned Python workspace, starts the project-owned PostgreSQL cluster under `.local`
on an owner-only Unix socket, passes that exact data root into the launchd-owned engine on
`127.0.0.1:8765`, builds `RSIAtlas`, stages `dist/RSIAtlas.app`, launches it, and verifies schema
`1.1.0` plus the exact degraded-only-model eight-component contract.

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
uv run ruff check packages services infra
uv run ruff format --check packages services infra
uv run mypy packages services infra
RSI_ATLAS_TEST_DATABASE_URL="$(./infra/local/postgres.sh test-url)" uv run pytest -q
uv run atlas doctor --json
swift test --package-path apps/macos
swift build --package-path apps/macos --product RSIAtlas
```

The product is research-only. It has no trading, wallet, signing, custody, or private-key authority.
