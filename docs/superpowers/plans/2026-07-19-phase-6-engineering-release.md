# Phase 6 Engineering and Release Maturity Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development
> (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use
> checkbox (`- [x]`) syntax for tracking.
>
> **Execution:** Follow repository TDD and review gates task by task. Do not claim Section 33
> criteria 85–134 closed. Do not redo Phases 2–5. Hard-block only on true Apple Developer
> signing/notarization secrets; document those blockers and continue every other development
> path. Prefer ordered slices: eval plane → Codex product gate → backup/restore/Safe Mode →
> packaging/signing honesty.

**Goal:** Qualify components via frozen offline evaluations, produce gated Codex patches from
sanitized bundles, and ship development release maturity (fail-closed release checks,
backup/restore/Safe Mode paths, unsigned packaging honesty, SBOM scripts)—without pretending
loopback HTTP, unsigned builds, or missing notarization secrets are release evidence.

**User-visible outcome:** Development loopback/CLI surfaces can (1) run an offline evaluation
harness over frozen fixture datasets with deterministic evaluators preceding blocked LLM judges,
(2) accept a sanitized Codex reproduction bundle and emit a candidate patch that fails closed
on automatic authority, (3) create/verify/restore a development workspace backup and enter Safe
Mode with collectors/models/parsers/migrations disabled, and (4) generate an SBOM + unsigned
package inventory while release checks honestly report `unsigned` / `notarization_blocked`.

**Architecture:** Keep Phases 1–5 immutable. Phase 6 adds (1) strict evaluation/Codex/recovery/
release contracts, (2) offline eval harness with fail-closed judge calibration, (3) Codex
product-plane gate (sanitize → approve → candidate patch; no merge/push/promote), (4) filesystem
backup barrier + Safe Mode capability mask + integrity scrub (development crypto; Keychain
wrapping documented as blocked), (5) SBOM from lockfile + fail-closed release checks that refuse
to claim signed/notarized without credentials. Native Studio labs UI and signed distribution
remain deferred.

**Tech Stack:** Python 3.11+, Pydantic strict contracts, existing pytest, stdlib hashlib/json/
pathlib/tarfile/hmac. **No new third-party dependency.** No Apple notarization APIs without
secrets. No automatic git push/merge.

## Global Constraints

1. Deterministic/code evaluators run **before** any LLM judge path; judges fail closed until
   labelled calibration sets exist (`blocked_judge_uncalibrated`).
2. Holdout split examples never enter prompt-tuning or judge-training paths.
3. Codex operates only in the engineering plane; cannot merge, push, deploy, publish research,
   promote evaluations, access Keychain, or open network in strict mode.
4. Sanitized reproduction bundles strip credentials, private PDFs, analyst notes, and Keychain
   material; redaction failures fail closed.
5. Candidate patches remain ungated for automatic authority; quality gate records pass/fail only.
6. Backup manifests are hash-verified; development encryption uses an explicit local passphrase
   (Keychain wrap remains `blocked_keychain_unavailable`).
7. Safe Mode disables collectors, models, parser workers, automatic migration, and workflow
   resumption.
8. Unsigned packaging must label itself `unsigned_development`; never claim notarized.
9. Release checks fail closed when signing identity / notarization credentials are absent.
10. Acceptance-matrix rows get **development partial** evidence only; no false criterion closure.
11. Failures are typed and sanitized; secrets never enter HTTP error bodies or Codex bundles.
12. No new dependency if stdlib + existing stack suffice.

## Development-slice acceptance (must prove)

1. Strict contracts reject invalid datasets, experiments, evaluator results, promotion outcomes,
   Codex bundles/patches, backup manifests, Safe Mode states, and release check reports.
2. Offline eval harness loads a frozen fixture dataset, runs schema → deterministic evaluators,
   and refuses LLM judges with `blocked_judge_uncalibrated`.
3. Promotion gate rejects on critical deterministic failure; records `reject` / `require_human_review`.
4. Sanitized Codex bundle builder redacts secrets and denies prohibited paths.
5. Codex gate records approval policy; `merge`/`push`/`deploy`/`promote_evaluation` always blocked.
6. Patch quality gate runs deterministic checks (schema, secret scan stub, unit-test stub hook)
   and never auto-applies.
7. Backup barrier freezes a workspace directory tree, writes hashed manifest, verifies round-trip.
8. Restore dry-run verifies manifest hashes before copy; tampered artifact fails closed.
9. Safe Mode capability mask disables collectors/models/parsers/auto-migration/workflow resume.
10. Integrity scrub detects missing or modified artifact files against a manifest.
11. SBOM script emits CycloneDX-ish JSON from `uv.lock` without network.
12. Release check reports `unsigned` / `notarization_blocked` and exits non-zero for release claim.
13. Loopback/CLI surfaces expose eval run, Codex gate, backup/restore, Safe Mode without claiming
    signed release.

## Explicitly out of scope (blocked / later)

- Apple Developer ID signing, notarization, stapling, Gatekeeper clean-user proof (needs secrets)
- Embedded CPython wheelhouse / nested signed helpers in `.app`
- Production Keychain-wrapped backup keys
- Calibrated LLM judges / labelled holdout promotion (criteria 55–56, 94–97 full close)
- Qualified live Codex App Server / local provider contract suite against a real Codex binary
- Native Evaluation / Codex laboratory Swift UI
- Criteria 85–134 closed as release evidence
- XPC replacing loopback HTTP

## Ordered slices

| Slice | Focus | Commit theme |
| --- | --- | --- |
| A | Eval plane contracts + offline harness + promotion gate | `feat: … evaluation …` |
| B | Codex sanitized bundle + approval + patch gate | `feat: … codex …` |
| C | Backup/restore/Safe Mode + integrity scrub | `feat: … recovery …` |
| D | SBOM + unsigned packaging honesty + release checks | `feat: … release …` |
| E | Loopback/CLI wiring + honest docs close | `docs: close Phase 6 …` |

---

## File structure

- `packages/contracts/src/rsi_atlas_contracts/{evaluation,codex,recovery,release}.py`
- `packages/contracts/tests/test_{evaluation,codex,recovery,release}.py`
- `packages/evaluation/` — offline harness, deterministic evaluators, promotion gate, judge stub
- `packages/engineering/` — sanitize, approval policy, patch gate (Codex product plane)
- `packages/recovery/` — backup barrier, restore, Safe Mode, integrity scrub
- `packages/release/` — SBOM builder, package inventory, release checks
- `script/{generate_sbom,release_check}.py`
- `services/engine/...` — loopback eval / engineering / recovery APIs (thin)
- `fixtures/evaluation/` — tiny frozen dataset
- README / production-plan / roadmap / acceptance-matrix — honest partial evidence only
- Delete stub: `2026-07-19-phase-6-engineering-release-stub.md` after this plan lands

---

### Task 1: Strict evaluation contracts

**Files:**

- Create: `packages/contracts/src/rsi_atlas_contracts/evaluation.py`
- Modify: `packages/contracts/src/rsi_atlas_contracts/__init__.py`
- Create: `packages/contracts/tests/test_evaluation.py`

**Interfaces (minimum):**

- `DatasetSplit` = development | calibration | regression | adversarial | holdout | shadow_production
- `EvaluationDataset` (dataset_id, version, purpose, task_family, splits, status, source_snapshot_hash)
- `EvaluatorKind` = schema | deterministic_rule | exact_numerical | retrieval_citation | statistical | llm_judge | human_review
- `EVALUATOR_ORDER` (immutable precedence; later cannot erase earlier failure)
- `EvaluatorResult` (kind, passed, failure_class, score optional)
- `ExperimentManifest` (frozen component versions + hardware class)
- `EvaluationRun` / `EvaluationRunStatus`
- `PromotionOutcome` = promote | promote_for_selected_task_only | continue_shadow_evaluation | reject | require_human_review
- `PromotionDecision` (outcome, critical_failure_count, reasons)
- `JudgeCalibrationStatus` / gate → always blocked in development (`blocked_judge_uncalibrated`)

- [x] **Step 1: Write RED contract tests**
- [x] **Step 2: Run RED**
- [x] **Step 3: Implement smallest strict models**
- [x] **Step 4: Verify and commit**

```bash
uv run pytest packages/contracts/tests/test_evaluation.py -q
uv run ruff check packages/contracts && uv run ruff format --check packages/contracts
uv run mypy packages/contracts/src
git commit -m "feat: define evaluation plane contracts"
```

---

### Task 2: Offline evaluation harness + promotion gate

**Files:**

- Create: `packages/evaluation/` workspace package
- Create: `packages/evaluation/src/rsi_atlas_evaluation/{harness,evaluators,promotion,judges}.py`
- Create: `packages/evaluation/tests/test_harness.py`, `test_evaluators.py`, `test_promotion.py`, `test_judges.py`
- Create: `fixtures/evaluation/retrieval_regression_v1.json`
- Modify: root `pyproject.toml` workspace members

- [x] **Step 1: RED** — fixture run executes schema+deterministic; judge blocked; critical fail → reject
- [x] **Step 2: Implement harness + gate**
- [x] **Step 3: GREEN + commit**

```bash
uv run pytest packages/evaluation/tests -q
git commit -m "feat: add offline evaluation harness and promotion gate"
```

---

### Task 3: Codex / engineering contracts

**Files:**

- Create: `packages/contracts/src/rsi_atlas_contracts/codex.py`
- Create: `packages/contracts/tests/test_codex.py`
- Modify: `__init__.py`

**Interfaces (minimum):**

- `CodexAuthorityAction` + `BLOCKED_CODEX_AUTHORITY` (merge, push, deploy, publish_research, promote_evaluation, trade, sign)
- `SanitizedReproductionBundle` (failure_summary, versions, sanitized inputs, expected/actual, validators, permitted_commands, redaction_report)
- `CodexApprovalDecision` / `CodexCommandClass` (read_source, inspect, file_change, test, dependency_install, network, commit)
- `CandidatePatch` (patch_id, bundle_id, diff_hash, status=`candidate`)
- `PatchQualityGateResult` (checks, passed, blocking_failures)
- Network/credential denial markers for strict mode

- [x] **Step 1: RED**
- [x] **Step 2: Implement**
- [x] **Step 3: Commit**

```bash
uv run pytest packages/contracts/tests/test_codex.py -q
git commit -m "feat: define Codex engineering plane contracts"
```

---

### Task 4: Sanitized bundle + Codex patch gate

**Files:**

- Create: `packages/engineering/` workspace package
- Create: `packages/engineering/src/rsi_atlas_engineering/{sanitize,approval,gate,authority}.py`
- Create: `packages/engineering/tests/test_sanitize.py`, `test_approval.py`, `test_gate.py`, `test_authority.py`

- [x] **Step 1: RED** — secret paths redacted; merge blocked; gate records fail without auto-apply
- [x] **Step 2: Implement**
- [x] **Step 3: GREEN + commit**

```bash
uv run pytest packages/engineering/tests -q
git commit -m "feat: add Codex sanitized bundle and fail-closed patch gate"
```

---

### Task 5: Recovery contracts (backup / Safe Mode / scrub)

**Files:**

- Create: `packages/contracts/src/rsi_atlas_contracts/recovery.py`
- Create: `packages/contracts/tests/test_recovery.py`

**Interfaces (minimum):**

- `BackupProductKind` = research_bundle | workspace | disaster_recovery
- `BackupManifest` (backup_id, kind, created_at, root_hash, entries[{path,sha256,size}], encryption_status)
- `BackupEncryptionStatus` = development_passphrase | blocked_keychain_unavailable | plaintext_dev_only
- `RestorePlan` / `RestoreVerification`
- `SafeModeState` + disabled capability set
- `IntegrityScrubFinding` / `IntegrityScrubReport`
- `DoctorHealthState` reuse-compatible statuses where needed

- [x] **Step 1–4: RED → implement → commit**

```bash
uv run pytest packages/contracts/tests/test_recovery.py -q
git commit -m "feat: define backup, Safe Mode, and integrity contracts"
```

---

### Task 6: Backup barrier, restore, Safe Mode, integrity scrub

**Files:**

- Create: `packages/recovery/` workspace package
- Create: `packages/recovery/src/rsi_atlas_recovery/{backup,restore,safe_mode,scrub}.py`
- Create: `packages/recovery/tests/test_backup.py`, `test_restore.py`, `test_safe_mode.py`, `test_scrub.py`

- [x] **Step 1: RED** — round-trip backup; tamper fails; Safe Mode disables caps; scrub finds missing file
- [x] **Step 2: Implement filesystem development paths**
- [x] **Step 3: GREEN + commit**

```bash
uv run pytest packages/recovery/tests -q
git commit -m "feat: add development backup, restore, Safe Mode, and integrity scrub"
```

---

### Task 7: Release contracts + SBOM + fail-closed release checks

**Files:**

- Create: `packages/contracts/src/rsi_atlas_contracts/release.py`
- Create: `packages/contracts/tests/test_release.py`
- Create: `packages/release/` workspace package
- Create: `packages/release/src/rsi_atlas_release/{sbom,inventory,checks}.py`
- Create: `packages/release/tests/test_sbom.py`, `test_inventory.py`, `test_checks.py`
- Create: `script/generate_sbom.py`, `script/release_check.py`

**Interfaces (minimum):**

- `SigningStatus` = unsigned_development | signed_developer_id | notarization_blocked | notarized
- `ReleaseCheckReport` (signing, notarization, sbom_present, entitlement_matrix, zero_egress, blockers)
- `PackageInventory` (bundle paths, python_embedded=false for now, honesty labels)
- `SbomDocument` (bom_format, components from lock)
- Release check exits non-zero if caller requests `--require-release` without secrets

- [x] **Step 1: RED**
- [x] **Step 2: Implement without secrets; hard-block notarization paths**
- [x] **Step 3: GREEN + commit**

```bash
uv run pytest packages/contracts/tests/test_release.py packages/release/tests -q
uv run python script/generate_sbom.py --out /tmp/atlas-sbom.json
uv run python script/release_check.py; test $? -ne 0  # fail-closed for release claim
git commit -m "feat: add SBOM generation and fail-closed unsigned release checks"
```

---

### Task 8: Loopback / CLI wiring

**Files:**

- Create: `services/engine/src/rsi_atlas_engine/{evaluation,engineering,recovery}.py` (ports)
- Modify: `services/engine/src/rsi_atlas_engine/api.py`, `cli.py` as needed
- Create: `services/engine/tests/test_phase6_api.py`
- Modify: engine `pyproject.toml` deps

**Endpoints (minimum, loopback only):**

- `POST /v1/evaluation:run` — offline harness
- `POST /v1/engineering/codex:gate` — sanitize + gate candidate
- `POST /v1/recovery/backup:create`, `POST /v1/recovery/backup:restore-verify`
- `POST /v1/recovery/safe-mode:enter`, `GET /v1/recovery/safe-mode`
- `POST /v1/release:check` — honesty report (never claims notarized)

- [x] **Step 1: RED**
- [x] **Step 2: Wire**
- [x] **Step 3: GREEN + commit**

```bash
uv run pytest services/engine/tests/test_phase6_api.py -q
git commit -m "feat: expose Phase 6 evaluation, Codex gate, and recovery loopback APIs"
```

---

### Task 9: Honest docs + Phase 6 development-slice close

**Files:**

- Modify: `README.md`, `docs/production-plan.md`, `docs/acceptance-matrix.md`,
  `docs/superpowers/plans/2026-07-18-full-product-delivery-roadmap.md`, this plan (checkboxes)
- Delete: `docs/superpowers/plans/2026-07-19-phase-6-engineering-release-stub.md`

- [x] **Step 1: Update evidence language (development partial only; list signing blockers)**
- [x] **Step 2: Full focused verification**
- [x] **Step 3: Commit close — do NOT push**

```bash
uv run pytest packages/contracts/tests/test_evaluation.py packages/contracts/tests/test_codex.py \
  packages/contracts/tests/test_recovery.py packages/contracts/tests/test_release.py \
  packages/evaluation/tests packages/engineering/tests packages/recovery/tests packages/release/tests \
  services/engine/tests/test_phase6_api.py -q
uv run ruff check packages/contracts packages/evaluation packages/engineering packages/recovery packages/release services/engine
uv run mypy packages/contracts/src packages/evaluation/src packages/engineering/src packages/recovery/src packages/release/src
git commit -m "docs: close Phase 6 engineering release development slice"
```

---

## Hard blockers (document; do not fake)

| Blocker | Why blocked | Unblock command for human |
| --- | --- | --- |
| Developer ID signing | No Apple team cert / identity in repo | Provide signing identity + unlock keychain |
| Notarization | No Apple ID / app-specific password / API key | Provide notarization credentials; run `xcrun notarytool` |
| Stapling / Gatekeeper clean-user | Depends on notarization | After notarize, staple and test on clean Mac |
| Keychain-wrapped backup keys | Needs Keychain access group design | After entitlement matrix review |
| Embedded signed Python runtime | Packaging + nested signing | After signing identity available |
| Live Codex App Server qualification | Needs installed Codex binary + provider | Provide local Codex + run contract suite |

## Self-review

1. **Spec coverage (§§25–32):** evaluation lifecycle, Codex plane, packaging honesty, backup/Safe
   Mode/scrub — each has a task. Signing/notarization remain explicit blockers.
2. **No placeholders:** tasks name files, interfaces, and commands.
3. **Ordered slices:** eval → Codex → recovery → packaging → docs.
4. **Honest closure:** criteria 85–134 stay open with development-partial evidence only.
