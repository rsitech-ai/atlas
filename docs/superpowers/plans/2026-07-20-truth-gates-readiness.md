# RSI Atlas Truth Gates And Readiness Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make Safe Mode and the Codex patch gate fail closed in real engine paths, then reconcile public/runtime readiness claims with exact-head evidence.

**Architecture:** Persist Safe Mode outside PostgreSQL under the owner-private runtime data root so it is available before database migrations. Read the state at each guarded operation boundary, cache one Phase 6 service per FastAPI application, and return a stable locked response when a capability is disabled. Replace the Codex default-true unit stub with strict diff-bound evidence; the current loopback API has no trusted runner, so it must return a failed gate until a runner is explicitly integrated.

**Tech Stack:** Python 3.12, Pydantic 2, FastAPI, PostgreSQL 17/pgvector, pytest, Swift 6/SwiftUI, GitHub Actions.

## Global Constraints

- Strict Offline is the default; no new network or hosted service dependency.
- Safe Mode disables collectors, models, parser workers, automatic migration, and workflow resumption.
- Safe Mode state must survive engine restart and must not depend on PostgreSQL availability.
- Corrupt or unsafe Safe Mode state fails closed.
- Codex remains engineering-plane only and cannot merge, push, deploy, publish research, or promote evaluations automatically.
- A submitted diff without trusted, matching test evidence cannot reach `gate_passed`.
- No acceptance criterion moves to `Proven` from source presence, development tests, or an unsigned artifact.
- No Apple credentials, repository transfer, public publication, or push is authorized by this plan.

---

### Task 1: Durable Safe Mode State And Capability Guard

**Files:**
- Modify: `packages/recovery/src/rsi_atlas_recovery/safe_mode.py`
- Modify: `packages/recovery/src/rsi_atlas_recovery/__init__.py`
- Create: `packages/recovery/tests/test_safe_mode_store.py`
- Modify: `packages/recovery/tests/test_backup_restore.py`

**Interfaces:**
- Produce: `SafeModeStore(path: Path)`, `SafeModeBlocked`, and `SafeModeController.require(capability)`.
- State path: `<data_root>/recovery/safe-mode.json`.

- [x] **Step 1: Write failing persistence and fail-closed tests**

  Cover missing state as inactive; enter/recreate as active; exit/recreate as inactive; mode `0600`; malformed, symlinked, overly permissive, and monkeypatched wrong-owner metadata as active fail-closed; and `require()` raising `SafeModeBlocked` for disabled capabilities.

- [x] **Step 2: Verify the tests fail for missing persistence APIs**

  Run: `uv run pytest packages/recovery/tests/test_safe_mode_store.py -q`

- [x] **Step 3: Implement descriptor-safe persistence**

  Write a fresh same-directory temporary file using `O_CREAT | O_EXCL | O_NOFOLLOW`, mode `0600`, `fsync`, atomic `os.replace`, and parent-directory `fsync`. Validate reads with `SafeModeState.model_validate_json`; unsafe or invalid state resolves to an active full capability mask with reason `safe_mode_state_unreadable`.

- [x] **Step 4: Verify recovery tests pass**

  Run: `uv run pytest packages/recovery/tests/test_safe_mode_store.py packages/recovery/tests/test_backup_restore.py -q`

### Task 2: Enforce Safe Mode At Engine Boundaries

**Files:**
- Create: `services/engine/src/rsi_atlas_engine/safe_mode.py`
- Modify: `services/engine/src/rsi_atlas_engine/phase6.py`
- Modify: `services/engine/src/rsi_atlas_engine/api.py`
- Modify: `services/engine/src/rsi_atlas_engine/ingestion.py`
- Modify: `services/engine/src/rsi_atlas_engine/research.py`
- Modify: `services/engine/src/rsi_atlas_engine/runtime.py`
- Modify: `packages/storage/src/rsi_atlas_storage/migrations.py`
- Modify: `services/engine/tests/test_phase6_api.py`
- Modify: `services/engine/tests/test_collectors_api.py`
- Modify: `services/engine/tests/test_document_processing_api.py`
- Modify: `services/engine/tests/test_research_api.py`
- Modify: `packages/storage/tests/test_postgres_integration.py`

**Interfaces:**
- Produce: `runtime_safe_mode(environ=None) -> SafeModeController` and a stable API error `423` with detail `Safe Mode blocks <capability>.`.
- Produce: `MigrationRunner.verify_all_applied()` for schema/checksum verification without DDL.

- [x] **Step 1: Write failing API and migration tests**

  Prove default `create_app()` retains state, app recreation over the same `RSI_ATLAS_DATA_ROOT` retains state, exit clears it, collector import and parser start are locked, observation/status reads remain available, workflow resume and model-backed research are locked, and Safe Mode schema verification performs no migration.

- [x] **Step 2: Verify red behavior**

  Run: `uv run pytest services/engine/tests/test_phase6_api.py services/engine/tests/test_collectors_api.py services/engine/tests/test_document_processing_api.py services/engine/tests/test_research_api.py -q`

  Expected: state-recreation and capability-lock assertions fail because the current service is in-memory and unguarded.

- [x] **Step 3: Cache one Phase 6 service and add boundary guards**

  Resolve one file-backed controller per application; guard collector mutation, processing start, model-backed research, and workflow start/resume. Add authenticated `POST /v1/recovery/safe-mode:exit`. Keep recovery/status/read-only evidence paths available.

- [x] **Step 4: Split migration verification from application**

  `verify_all_applied()` must check the exact expected versions and hashes without creating tables or executing migration SQL. Automatic service composition uses apply only when `AUTOMATIC_MIGRATION` is enabled; runtime diagnostics use verify-only while Safe Mode is active.

- [x] **Step 5: Verify focused engine/storage tests pass**

  Run: `RSI_ATLAS_TEST_DATABASE_URL="$(./infra/local/postgres.sh test-url)" uv run pytest services/engine/tests/test_phase6_api.py services/engine/tests/test_collectors_api.py services/engine/tests/test_document_processing_api.py services/engine/tests/test_research_api.py packages/storage/tests/test_postgres_integration.py -q`

### Task 3: Fail-Closed Diff-Bound Codex Gate

**Files:**
- Modify: `packages/contracts/src/rsi_atlas_contracts/codex.py`
- Modify: `packages/contracts/src/rsi_atlas_contracts/__init__.py`
- Modify: `packages/engineering/src/rsi_atlas_engineering/gate.py`
- Modify: `services/engine/src/rsi_atlas_engine/phase6.py`
- Modify: `packages/contracts/tests/test_codex.py`
- Modify: `packages/engineering/tests/test_engineering.py`
- Modify: `services/engine/tests/test_phase6_api.py`

**Interfaces:**
- Produce: strict `PatchTestEvidence` bound to `patch_id` and `diff_hash`, with an allowlisted suite identifier, fixed argv tuple, exit code, timestamps, bounded output hashes, and runner version.
- Change: `run_patch_quality_gate(..., test_evidence: tuple[PatchTestEvidence, ...] = ())` has no default-true boolean.

- [x] **Step 1: Write failing contract and gate tests**

  Missing evidence, non-zero evidence, mismatched patch/diff, stale evidence, and caller-injected evidence through the current API must fail. A directly supplied valid trusted evidence object may pass the unit-evidence check while all authority denials remain intact.

- [x] **Step 2: Verify the current default-true behavior fails the new tests**

  Run: `uv run pytest packages/contracts/tests/test_codex.py packages/engineering/tests/test_engineering.py services/engine/tests/test_phase6_api.py -q`

- [x] **Step 3: Implement the strict evidence contract and gate validation**

  Recompute `sha256(diff_text)` and require it to equal the patch diff hash. Validate every evidence object against both patch identity fields and successful execution. Rename the check from `unit_stub` to `unit_test_evidence`.

- [x] **Step 4: Keep the current API safely blocked**

  `Phase6Service.codex_gate()` supplies no evidence until a trusted local worktree runner exists, so a clean caller-provided diff returns `gate_failed`; it must never accept caller-provided `passed`, argv, or evidence JSON as proof.

- [x] **Step 5: Verify Codex tests pass**

  Run the command from Step 2 and inspect the serialized gate result.

### Task 4: Reconcile Runtime And Repository Truth

**Files:**
- Modify: `apps/macos/Sources/RSIAtlasApp/Views/CommandCenterView.swift`
- Modify: `services/engine/src/rsi_atlas_engine/runtime.py`
- Modify: `apps/macos/Tests/RSIAtlasAppTests/RuntimePresentationTests.swift`
- Modify: `services/engine/tests/test_runtime.py`
- Modify: `docs/production-plan.md`
- Modify: `docs/superpowers/plans/2026-07-18-full-product-delivery-roadmap.md`
- Modify: `docs/acceptance-matrix.md`
- Modify: `docs/release/signing-notarization-blockers.md`
- Modify: `SECURITY.md`
- Modify: `.github/workflows/ci.yml`

**Interfaces:**
- User-facing phrase: `Local runtime health` rather than `Live readiness`.
- Security contact: `info@rsitech.ai`.
- Readiness state: development-complete/partially runtime-proven; production, package, signing, notarization, and clean-install proof remain open.

- [x] **Step 1: Add red copy assertions**

  Assert the current runtime status no longer contains `Phase 1`, and Swift presentation uses the scoped local-runtime wording.

- [x] **Step 2: Update exact-head truth surfaces**

  Replace the Phase 2A-only production brief, mark the old roadmap evidence boundary historical, add a dated exact-head development verification row without moving acceptance status, relabel signing blockage as mixed repo/owner/external, and replace the security placeholder.

- [x] **Step 3: Strengthen deterministic CI evidence**

  Set `UV_PYTHON: "3.12"`, lint `script` and `tests`, run parser-governance verification, and run macOS document-worker containment tests. Keep full PostgreSQL and signed-release gaps explicit.

- [x] **Step 4: Verify focused copy/docs/CI checks**

  Run: `uv run pytest services/engine/tests/test_runtime.py -q`

  Run: `swift test --package-path apps/macos --filter RuntimePresentationTests`

  Run: `ruby -e 'require "yaml"; YAML.load_file(".github/workflows/ci.yml", aliases: true)'`

  Run: `rg -n 'SECURITY_CONTACT_EMAIL_PLACEHOLDER|Live readiness|unavailable in Phase 1' SECURITY.md apps/macos services/engine docs`

  Expected: no matches.

  Run: `uv run ruff check packages services infra script tests && uv run python script/audit_pdf_parser_dependencies.py verify`

### Task 5: Full Verification And Evidence Ledger

**Files:**
- Modify: `docs/production-plan.md`
- Modify: `docs/acceptance-matrix.md`

- [x] **Step 1: Run static and contract gates**

  Run lock, Ruff check/format, strict mypy, parser governance, and `git diff --check`.

- [x] **Step 2: Run full Python/PostgreSQL twice and Swift once**

  Run `RSI_ATLAS_TEST_DATABASE_URL="$(./infra/local/postgres.sh test-url)" uv run pytest -q` twice, then `swift test` and the Swift product build.

- [x] **Step 3: Run real development and release-IPC smokes**

  Run `./script/build_and_run.sh --verify`; then run the authenticated release-IPC readiness smoke without claiming signing or packaging proof.

- [x] **Step 4: Record only observed evidence**

  Update the dated ledger with the final commit, exact commands/results, remaining ONNX skip, and unchanged production/release blockers.

- [ ] **Step 5: Independent whole-branch review**

  Review the full branch diff for false readiness claims, capability bypasses, unsafe persistence, missing red-green evidence, and test gaps. Fix all Critical/Important findings and re-run affected checks.
