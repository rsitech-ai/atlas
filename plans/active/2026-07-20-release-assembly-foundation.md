# Release Assembly Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:executing-plans` to implement
> this plan task-by-task. Every production change follows red-green-refactor.

## Goal

- User-visible outcome: RSI Atlas can assemble a versioned, inspectable macOS application shell
  from a release Swift build while the release gate names every missing embedded-runtime component
  and refuses signing, notarization, or publication until the bundle is self-contained.
- How to see it working: `script/assemble_release_app.py` creates a deterministic bundle structure
  with version, legal notices, SBOM, and a machine-readable assembly manifest; `release_check.py
  --require-release` reports exact runtime blockers and exits nonzero.

## Current State

- Relevant paths: `packages/release/src/rsi_atlas_release/`, `packages/release/tests/`,
  `script/package_release.sh`, `script/sign_and_notarize.sh`, `apps/macos`, and `docs/release/`.
- Existing behavior: the development runner stages only a Swift executable and unversioned plist;
  the release check stays false but does not enumerate the missing embedded Python, engine, or
  PostgreSQL/pgvector runtime; the signing helper uses shallow `codesign --deep`.
- Constraints: outside-Mac-App-Store Developer ID distribution; Strict Offline by default; no
  system Python, Homebrew, global packages, or container dependency; nested code signs inside-out;
  no release asset without notarization, stapling, Gatekeeper, and clean-user proof.

## Target State

- Desired behavior:
  - `assemble_release_app(...)` creates `Contents/MacOS/RSIAtlas`, a versioned `Info.plist`, legal
    notices, CycloneDX SBOM, and `Contents/Resources/release-assembly.json`.
  - `inspect_runtime_completeness(...)` requires fixed in-bundle entry points for embedded Python,
    the engine launcher, PostgreSQL, and pgvector and returns stable blocker codes.
  - The release checker propagates those blocker codes and refuses readiness.
  - The signing helper verifies runtime completeness before changing signatures, signs discovered
    nested Mach-O code inside-out with hardened runtime and timestamping, verifies each signature,
    notarizes, staples, recreates the final archive, and writes a SHA-256 checksum.
- Non-goals: embedding CPython/PostgreSQL in this slice, creating notary credentials, App Store
  upload, publishing an unnotarized artifact, or weakening resource/model/owner-sealed gates.

## Risks and Failure Modes

- A visually complete shell can be mistaken for a standalone product; the assembly manifest and
  release checker must retain explicit `runtime_complete=false` truth.
- Signing order can invalidate outer signatures; inventory nested Mach-O code and sign deepest
  paths first, then the main executable, then the app.
- Reassembly can overwrite an unrelated path; accept only an output path ending in `.app`, stage in
  a sibling temporary directory, and atomically replace only the exact destination.
- A notarized pre-staple archive is not the downloadable artifact; recreate the archive after
  stapling and checksum that final archive.

## Milestones

### M1. Runtime completeness contract

- Goal: make the first package blocker machine-readable and regression-protected.
- Files / systems: create `packages/release/src/rsi_atlas_release/assembly.py`; modify
  `packages/release/src/rsi_atlas_release/__init__.py` and `checks.py`; extend
  `packages/release/tests/test_release_checks.py`.
- Changes: define `REQUIRED_RUNTIME_COMPONENTS`, `inspect_runtime_completeness(bundle_path)`, and
  stable blockers `embedded_python_missing`, `engine_launcher_missing`, `postgresql_missing`, and
  `pgvector_missing`; propagate them into `ReleaseCheckReport.blockers`.
- Verification: write the missing-runtime and complete-fixture tests first; observe the focused test
  fail because the interface is absent; implement the minimum pure inspection logic; rerun focused
  tests, Ruff, format, and strict mypy.
- Expected result: the existing two-file shell fails for exact repository blockers rather than a
  generic readiness constant.

### M2. Versioned atomic app-shell assembly

- Goal: replace ad hoc plist generation with one release-specific assembler without changing the
  development runner.
- Files / systems: extend `assembly.py` and release tests; create
  `script/assemble_release_app.py`; modify `script/package_release.sh`.
- Changes: implement
  `assemble_release_app(source_executable, destination_bundle, version, build_number, repo_root)`;
  validate inputs; stage in a sibling temporary directory; write the bundle plist and resources;
  record file hashes and runtime blockers in canonical JSON; atomically replace the exact `.app`.
- Verification: tests first cover version metadata, executable mode/hash, legal/SBOM resources,
  manifest determinism, unsafe destination rejection, and replacement of only the exact bundle;
  then run the CLI against a release Swift build and inspect the resulting plist/manifest.
- Expected result: a reproducible latest development shell exists locally but remains explicitly
  non-release-ready because runtime components are absent.

### M3. Fail-closed nested signing workflow

- Goal: prevent shallow signing and ensure the downloadable archive is the stapled artifact.
- Files / systems: modify `script/sign_and_notarize.sh`; add
  `packages/release/tests/test_signing_script_contract.py`; update release docs.
- Changes: preflight runtime completeness; enumerate Mach-O files; sign deepest nested code first
  with `--options runtime --timestamp`; sign app last; verify nested and outer signatures; submit a
  temporary notarization archive; staple and validate; recreate the final archive; emit SHA-256.
- Verification: contract tests first fail against `--deep`; shell syntax passes; missing runtime
  stops before `codesign`; missing notary variables stop before bundle mutation. Actual notarization
  remains gated on owner-supplied API-key credentials.
- Expected result: the script is safe to use once the embedded runtime exists and cannot bless the
  current shell.

### M4. Review and publication gate

- Goal: merge only the bounded release-foundation behavior through a reviewed PR.
- Files / systems: branch, full regression, PR, public repository.
- Changes: archive this plan with exact evidence; open a PR; remediate Critical/Important findings;
  merge only if local regression is green and hosted-CI status is stated exactly.
- Verification: `script/codex_full_regression.sh`, history secret scan, PR diff review, exact merged
  SHA, and public clone connectivity.
- Expected result: public `main` gains a truthful assembly foundation; no GitHub release asset is
  created until the runtime and notary gates pass.

## Verification

- `uv run pytest packages/release/tests -q`
- `uv run ruff check packages/release script tests`
- `uv run ruff format --check packages/release script tests`
- `uv run mypy packages/release script`
- `bash -n script/package_release.sh script/sign_and_notarize.sh`
- `swift build -c release --package-path apps/macos --product RSIAtlas`
- `uv run python script/assemble_release_app.py --build-number 1`
- `uv run python script/release_check.py --require-release` must exit nonzero with exact embedded
  runtime blockers until M1-M3 prerequisites are present.
- `./script/codex_full_regression.sh`

## Decision Log

- 2026-07-20: Reuse the approved Section 31 release architecture; do not invent a competing package
  shape or ask for a second product-design approval.
- 2026-07-20: Build a truthful app-shell assembler and exact runtime blockers before attempting to
  embed large runtimes; this is independently reviewable and prevents misleading release assets.
- 2026-07-20: Use the installed Developer ID Application identity for Team `2NY8A789TN` only after
  runtime completeness passes; no certificate download is needed.
- 2026-07-20: Keep notarization and public download blocked until an App Store Connect API private
  key is locally available and end-to-end artifact proof passes.

## Progress Log

- 2026-07-20: Public org repository and PR #1 publication completed on protected `main`.
- 2026-07-20: Release inventory confirmed the current shell lacks embedded Python, engine,
  PostgreSQL/pgvector, release metadata, nested signing, notarization, and clean-user proof.
- 2026-07-20: M1 red confirmed the runtime-completeness API was absent. M1 green now defines four
  fixed embedded-runtime paths, propagates their stable blocker codes into the release report, and
  passes seven release tests plus Ruff, format, strict mypy, and diff checks.
- 2026-07-20: M2 red confirmed the assembler and CLI did not exist. M2 green atomically stages a
  versioned Swift shell with legal files, SBOM, executable hash, and deterministic honesty manifest;
  `package_release.sh` assembles before the release gate. Thirteen release tests and static/type
  checks pass. A real release Swift build assembled version `0.1.0` build `1`; release checking
  correctly exited 1 with the four runtime blockers plus signing and notarization blockers.
- 2026-07-20: Next: commit M2, then execute M3 with failing signing-workflow contract tests.

## Rollback / Recovery

- If assembly tests fail: remove only the new assembler call and keep the existing fail-closed
  release checker; do not publish the staged shell.
- If signing preflight mutates an incomplete bundle: restore the app from a fresh assembly run and
  treat the signing script as blocked until the mutation test is fixed.
- Safe fallback: retain public `main` at the PR #1 merge and publish no release asset.
