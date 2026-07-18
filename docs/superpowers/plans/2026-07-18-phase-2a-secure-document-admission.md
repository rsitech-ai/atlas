# Phase 2A Secure Document Admission Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Import a local PDF from the native app or CLI into immutable quarantine, run deterministic bounded checks, and durably report awaiting-review, rejection, or exact-duplicate outcomes without admitting, parsing, or making any content searchable.

**Architecture:** A strict acquisition contract crosses Swift, API, service, and storage boundaries. Swift uploads from a coordinated file URL and the engine streams into an owner-private staging file before publishing the raw artifact into the existing content-addressed store. A pure policy evaluates explicit pass/fail/unknown safety checks without network, subprocess, model, or parser execution; any unknown mandatory signal prevents admission. PostgreSQL records append-only acquisitions, decisions, duplicate relationships, and outbox events transactionally. The native Evidence surface renders the durable decision, while admission and publication remain impossible in this slice.

**Tech Stack:** Python 3.11+, Pydantic 2.13.4, FastAPI 0.139.2, psycopg 3.3.4, PostgreSQL 17.10, Swift 6/SwiftUI, PDFKit only for native file type selection, pytest 9.1.1, Swift Testing.

## Global Constraints

- Preserve strict offline behavior: no DNS, external TCP, telemetry, model, parser, OCR, VLM, or monitored-source access.
- Preserve the non-trading boundary: no wallet, signing, private-key, exchange, transaction-submission, or trade capability.
- Treat every input PDF as untrusted; the engine streams at most 32 MiB and never follows a user-supplied server-side path or buffers the entire payload in memory.
- Store raw bytes before admission and never mutate or delete them as part of an admission decision.
- Do not expose admitted content to retrieval; this slice has no `PUBLISHED` transition or index write.
- All new Pydantic and Swift boundary models reject unknown fields and use schema version `1.0.0`.
- Every durable command carries tenant, workspace, actor, trace, and acquisition identities.
- Phase 2A cannot produce `ADMITTED`, `accept`, `accept_with_restrictions`, or `register_new_version`; every mandatory PDF safety signal must be authoritative before those transitions are enabled in Phase 2B.
- Exact content duplicates resolve by artifact hash inside the workspace. Filename or locator similarity never implies duplication or version lineage.
- No push, PR, release, signing, notarization, dependency installation, or external write is authorized.

---

## File Structure

- `packages/contracts/src/rsi_atlas_contracts/acquisition.py`: strict acquisition, lifecycle, safety-profile, decision, and durable-result contracts.
- `packages/ingestion/src/rsi_atlas_ingestion/admission.py`: pure deterministic pass/fail/unknown safety policy.
- `packages/ingestion/src/rsi_atlas_ingestion/service.py`: raw-artifact-first orchestration and idempotent durable command boundary.
- `packages/storage/src/rsi_atlas_storage/acquisition_repository.py`: tenant/workspace-scoped transactional acquisition, duplicate, decision, and outbox persistence.
- `migrations/0003_document_admission.sql`: append-only acquisition, admission-decision, duplicate-link, and outbox tables plus immutability triggers.
- `services/engine/src/rsi_atlas_engine/ingestion.py`: environment composition shared by CLI and API.
- `services/engine/src/rsi_atlas_engine/api.py`: bounded raw-body document admission endpoint.
- `services/engine/src/rsi_atlas_engine/cli.py`: direct local `atlas import-pdf` command.
- `apps/macos/Sources/RSIAtlasCore/Models/DocumentAdmission.swift`: strict cross-language response contract.
- `apps/macos/Sources/RSIAtlasCore/Services/DocumentImportClient.swift`: raw PDF request transport.
- `apps/macos/Sources/RSIAtlasCore/Stores/DocumentImportStore.swift`: latest-request-wins import state and typed failure evidence.
- `apps/macos/Sources/RSIAtlasApp/Views/EvidenceImportView.swift`: native file importer and truthful durable-result presentation.

---

### Task 1: Strict acquisition and admission contracts

**Files:**
- Create: `packages/contracts/src/rsi_atlas_contracts/acquisition.py`
- Modify: `packages/contracts/src/rsi_atlas_contracts/__init__.py`
- Create: `packages/contracts/tests/test_acquisition.py`

**Interfaces:**
- Consumes: `ArtifactCommandContext`, `ArtifactID`, and `StrictModel`.
- Produces: `AcquisitionMethod`, `NetworkProfile`, `DocumentLifecycle`, `AdmissionOutcome`, `SafetyCheckState`, `PDFSafetyProfile`, `AcquisitionRequest`, and `DocumentAdmissionRecord`.

- [ ] **Step 1: Write strict enum and model RED tests**

```python
def test_acquisition_request_rejects_unknown_fields() -> None:
    with pytest.raises(ValidationError):
        AcquisitionRequest.model_validate(
            {
                "schema_version": "1.0.0",
                "acquisition_id": str(uuid4()),
                "method": "manual_native",
                "original_filename": "paper.pdf",
                "source_locator": "file:paper.pdf",
                "declared_media_type": "application/pdf",
                "collector_version": "native-0.1.0",
                "network_profile": "offline",
                "unexpected": True,
            }
        )


def test_admission_record_cannot_claim_published() -> None:
    assert "published" not in {state.value for state in DocumentLifecycle}
```

- [ ] **Step 2: Run contract tests and verify RED**

Run: `uv run pytest packages/contracts/tests/test_acquisition.py -q`

Expected: collection fails because `rsi_atlas_contracts.acquisition` does not exist.

- [ ] **Step 3: Implement the exact boundary models**

```python
class AcquisitionMethod(StrEnum):
    MANUAL_NATIVE = "manual_native"
    MANUAL_CLI = "manual_cli"
    LOCAL_API = "local_api"


class NetworkProfile(StrEnum):
    OFFLINE = "offline"


class DocumentLifecycle(StrEnum):
    QUARANTINED = "quarantined"
    AWAITING_REVIEW = "awaiting_review"
    REJECTED = "rejected"
    DUPLICATE = "duplicate"


class AdmissionOutcome(StrEnum):
    ACCEPT = "accept"
    ACCEPT_WITH_RESTRICTIONS = "accept_with_restrictions"
    REQUEST_PASSWORD = "request_password"
    QUARANTINE_FOR_REVIEW = "quarantine_for_review"
    REJECT_POLICY_VIOLATION = "reject_policy_violation"
    REJECT_UNSAFE = "reject_unsafe"
    MARK_EXACT_DUPLICATE = "mark_exact_duplicate"
    REGISTER_NEW_VERSION = "register_new_version"


class SafetyCheckState(StrEnum):
    PASS = "pass"
    FAIL = "fail"
    UNKNOWN = "unknown"


class AcquisitionRequest(StrictModel):
    schema_version: Literal["1.0.0"] = "1.0.0"
    acquisition_id: UUID
    method: AcquisitionMethod
    original_filename: str = Field(min_length=1, max_length=255)
    source_locator: str = Field(min_length=1, max_length=1024)
    declared_media_type: Literal["application/pdf"]
    collector_version: str = Field(pattern=r"^[a-z0-9][a-z0-9._-]{0,63}$")
    network_profile: Literal[NetworkProfile.OFFLINE] = NetworkProfile.OFFLINE
```

The full `AdmissionOutcome` enum remains versioned for later Phase 2 workers, but this slice validates that only `quarantine_for_review`, `request_password`, `reject_policy_violation`, `reject_unsafe`, and `mark_exact_duplicate` can appear in a Phase 2A result. `PDFSafetyProfile` records exact byte size, SHA-256, header/EOF evidence, and explicit `pass`, `fail`, or `unknown` states for MIME/signature consistency, page limit, encryption/password state, malformed structures, embedded files, active actions, suspicious references, decompression ratio, source policy, and available disk. `DocumentAdmissionRecord` includes context, request, artifact descriptor, lifecycle, outcome, profile, reason codes, duplicate target when applicable, and recorded time. Add validators for the lifecycle/outcome matrix, artifact/profile hash and size agreement, and duplicate-target consistency.

- [ ] **Step 4: Cover every consistency boundary**

Add table-driven tests for every Phase 2A outcome, attempts to emit forbidden accept/admitted/new-version states, empty or control-character filenames, absolute/path-traversal filenames, duplicate reason entries, inconsistent lifecycle, mismatched artifact/profile evidence, and non-UTC timestamps. Original filenames must be leaf names after Unicode NFC normalization. The locator is an opaque `manual-import:<UUID>` value; never persist an absolute local path.

- [ ] **Step 5: Run focused and package verification**

Run:

```bash
uv run pytest packages/contracts/tests -q
uv run ruff check packages/contracts
uv run ruff format --check packages/contracts
uv run mypy packages/contracts/src
```

Expected: all commands pass and the prior artifact/status contracts remain unchanged.

- [ ] **Step 6: Commit Task 1**

```bash
git add packages/contracts
git commit -m "feat: define document admission contracts"
```

---

### Task 2: Deterministic fail-closed PDF quarantine policy

**Files:**
- Create: `packages/ingestion/pyproject.toml`
- Create: `packages/ingestion/src/rsi_atlas_ingestion/__init__.py`
- Create: `packages/ingestion/src/rsi_atlas_ingestion/admission.py`
- Create: `packages/ingestion/tests/test_admission.py`
- Modify: `pyproject.toml`

**Interfaces:**
- Consumes: `PDFSafetyProfile`, `AcquisitionRequest`, and exact-duplicate evidence.
- Produces: `PDFAdmissionPolicy.evaluate(profile: PDFSafetyProfile, request: AcquisitionRequest, duplicate_of: UUID | None) -> PDFAdmissionDecision`, where the decision contains a Phase 2A outcome and stable reason codes.

- [ ] **Step 1: Write policy RED tests with generated minimal PDFs**

```python
def _minimal_pdf(*, body: bytes = b"", pages: int = 1) -> bytes:
    page_objects = b"\n".join(b"/Type /Page" for _ in range(pages))
    return b"%PDF-1.7\n" + page_objects + b"\n" + body + b"\n%%EOF\n"


@pytest.mark.parametrize(
    ("profile", "outcome", "reason"),
    [
        (_profile(signature="fail"), AdmissionOutcome.REJECT_UNSAFE, "pdf_signature_invalid"),
        (_profile(encryption="fail"), AdmissionOutcome.REQUEST_PASSWORD, "pdf_encrypted"),
        (_profile(active_actions="fail"), AdmissionOutcome.QUARANTINE_FOR_REVIEW, "active_content_detected"),
        (_profile(decompression_ratio="unknown"), AdmissionOutcome.QUARANTINE_FOR_REVIEW, "required_check_unknown"),
    ],
)
def test_policy_outcomes_are_fail_closed(profile: PDFSafetyProfile, outcome: AdmissionOutcome, reason: str) -> None:
    decision = PDFAdmissionPolicy().evaluate(profile, _request(), duplicate_of=None)
    assert decision.outcome is outcome
    assert reason in decision.reason_codes
```

- [ ] **Step 2: Run focused tests and verify RED**

Run: `uv run pytest packages/ingestion/tests/test_admission.py -q`

Expected: collection fails because the ingestion package is absent.

- [ ] **Step 3: Implement bounded deterministic inspection**

The policy first returns `mark_exact_duplicate` for a verified same-workspace artifact. Otherwise a failed signature/MIME/source-policy check is rejected, an authoritative encrypted/password signal requests a password, any failed active-content/embedded-file/reference check is quarantined, and any mandatory `unknown` check is quarantined with `required_check_unknown`. Even an all-pass synthetic profile remains quarantined with `isolated_profiler_not_promoted` because Phase 2A has no promoted safety-profiler identity. The policy performs no byte parsing, filesystem read, network, subprocess, model, or clock work.

- [ ] **Step 4: Prove resource and false-positive boundaries**

Test every mandatory check as unknown, every fail priority, verified duplicate precedence, conflicting duplicate evidence, attempted all-pass admission, filename normalization, and deterministic output for identical profiles. Monkeypatch filesystem/socket/subprocess entry points to fail if invoked.

- [ ] **Step 5: Render and visually verify the clean-looking quarantine fixture**

Write the born-digital test fixture only under `tmp/pdfs/`, render it with:

```bash
pdftoppm -png tmp/pdfs/admission-born-digital.pdf tmp/pdfs/admission-born-digital
```

Inspect the PNG for a legible one-page fixture with no clipping or malformed glyphs. Its Phase 2A result must still be `awaiting_review`, not admitted. Remove only the exact `tmp/pdfs/` intermediates after recording the fixture hash in the task report; do not commit generated screenshots.

- [ ] **Step 6: Run package verification and commit Task 2**

```bash
uv lock --check
uv run pytest packages/ingestion/tests -q
uv run ruff check packages/ingestion
uv run ruff format --check packages/ingestion
uv run mypy packages/ingestion/src
git add pyproject.toml uv.lock packages/ingestion
git commit -m "feat: add deterministic PDF admission policy"
```

---

### Task 3: Streaming CAS publication and append-only acquisition persistence

**Files:**
- Create: `migrations/0003_document_admission.sql`
- Create: `packages/storage/src/rsi_atlas_storage/acquisition_repository.py`
- Modify: `packages/storage/src/rsi_atlas_storage/artifact_store.py`
- Modify: `packages/storage/src/rsi_atlas_storage/__init__.py`
- Modify: `packages/storage/tests/test_postgres_integration.py`

**Interfaces:**
- Consumes: `ArtifactCommandContext`, verified `ArtifactDescriptor`, `AcquisitionRequest`, `PDFAdmissionDecision`, and `PostgresDatabase`.
- Produces: bounded staged-file CAS publication plus `AcquisitionRepository.record(...) -> DocumentAdmissionRecord` with idempotent acquisition identity, exact duplicate linking, append-only history, and a transactional outbox event.

- [ ] **Step 1: Write migration and repository RED tests**

```python
def test_exact_duplicate_links_existing_acquisition_without_second_payload(
    postgres_database: PostgresDatabase, artifact_store: ContentAddressedArtifactStore
) -> None:
    repository = AcquisitionRepository(postgres_database)
    first = repository.record(context=_context(), request=_request(), descriptor=_artifact(), decision=_review())
    duplicate = repository.record(
        context=first.context,
        request=_request(acquisition_id=uuid4()),
        descriptor=first.artifact,
        decision=_review(),
    )
    assert duplicate.outcome is AdmissionOutcome.MARK_EXACT_DUPLICATE
    assert duplicate.duplicate_of_acquisition_id == first.request.acquisition_id
    assert _artifact_payload_count(artifact_store, first.artifact.artifact_id) == 1
```

Also add REDs for bounded streaming without full-payload buffering, short/read-failure staging cleanup, same acquisition replay, same acquisition ID with different hash, concurrent duplicate commands, cross-workspace duplicate isolation, decision/outbox atomicity, and UPDATE/DELETE/TRUNCATE rejection.

- [ ] **Step 2: Run PostgreSQL tests and verify RED**

Run:

```bash
RSI_ATLAS_TEST_DATABASE_URL="$(./infra/local/postgres.sh test-url)" \
  uv run pytest packages/storage/tests/test_postgres_integration.py -q
```

Expected: migration count and repository imports fail because migration `0003` and the repository do not exist.

- [ ] **Step 3: Add the append-only schema**

Create `atlas_ingestion.document_acquisitions`, `atlas_ingestion.document_admission_decisions`, `atlas_ingestion.document_duplicate_links`, and `atlas_ingestion.outbox_events`. Scope primary and foreign keys by tenant/workspace. Use a unique acquisition idempotency key and a workspace-scoped artifact index. Store constrained outcome/lifecycle text, reason arrays, profile/request snapshots as canonical JSONB, actor/trace IDs, and UTC timestamps. Add triggers rejecting UPDATE, DELETE, and TRUNCATE on evidence tables; outbox delivery metadata is appended as events rather than mutating evidence.

- [ ] **Step 4: Implement one-transaction lineage resolution**

Extend `ContentAddressedArtifactStore` with a descriptor-relative `put_file` path that opens one already-staged regular file with `O_NOFOLLOW`, hashes and copies it in bounded chunks into the existing atomic CAS publication path, verifies size before/after, and never owns or deletes the source staging file. `record` validates all boundary models, takes a transaction-scoped advisory lock derived from tenant/workspace/acquisition, and follows this order:

1. Return an exact prior record when acquisition ID and immutable request/artifact fingerprints match.
2. Raise `AcquisitionConflictError` when that acquisition ID already names different evidence.
3. Find an exact prior artifact acquisition in the workspace and record `mark_exact_duplicate` linked to it.
4. Insert the acquisition, append-only decision, optional duplicate link, and one `DocumentAdmissionRecorded` outbox event in the same transaction.
5. Reconstruct and strictly validate `DocumentAdmissionRecord` from stored values before commit.

- [ ] **Step 5: Run migration, concurrency, and full storage checks**

```bash
RSI_ATLAS_TEST_DATABASE_URL="$(./infra/local/postgres.sh test-url)" \
  uv run pytest packages/storage/tests -q
uv run ruff check packages/storage
uv run ruff format --check packages/storage
uv run mypy packages/storage/src
```

Expected: migration ledger contains `0001`, `0002`, and `0003`; all existing immutability and tenancy tests pass. Move the checked-in expected migration versions into `MigrationRunner` so runtime readiness and tests consume one source rather than duplicating `0001`/`0002` constants.

- [ ] **Step 6: Commit Task 3**

```bash
git add migrations packages/storage
git commit -m "feat: persist immutable document admissions"
```

---

### Task 4: Raw-artifact-first service, CLI, and bounded local API

**Files:**
- Create: `packages/ingestion/src/rsi_atlas_ingestion/service.py`
- Create: `packages/ingestion/tests/test_service.py`
- Create: `services/engine/src/rsi_atlas_engine/ingestion.py`
- Modify: `services/engine/src/rsi_atlas_engine/api.py`
- Modify: `services/engine/src/rsi_atlas_engine/cli.py`
- Create: `services/engine/tests/test_ingestion_api.py`
- Modify: `services/engine/tests/test_cli.py`

**Interfaces:**
- Consumes: raw PDF bytes plus strict metadata/context.
- Produces: `DocumentAdmissionService.admit(...) -> DocumentAdmissionRecord`, CLI JSON, and `POST /v1/workspaces/{workspace_id}/documents:admit`.

- [ ] **Step 1: Write raw-first and boundary RED tests**

```python
def test_service_retains_raw_artifact_when_policy_requests_review() -> None:
    result = service.admit(context=context, request=request, payload=suspicious_pdf)
    assert result.lifecycle is DocumentLifecycle.AWAITING_REVIEW
    assert artifact_store.verify(result.artifact.artifact_id, context=context) == result.artifact


def test_api_rejects_oversized_body_without_calling_service() -> None:
    response = client.post(
        f"/v1/workspaces/{workspace_id}/documents:admit",
        headers=_headers(content_length=33_554_433),
        content=b"",
    )
    assert response.status_code == 413
    assert fake_service.calls == []
```

Cover missing/duplicate identity headers, wrong content type, invalid UUIDs, body stream exceeding the declared size, absent content length, acquisition conflict 409, policy rejection as durable 200 evidence, database failure as 503 with no fabricated record, and strict response validation.

- [ ] **Step 2: Run engine/service tests and verify RED**

Run: `uv run pytest packages/ingestion/tests/test_service.py services/engine/tests/test_ingestion_api.py services/engine/tests/test_cli.py -q`

Expected: the service, route, and CLI command do not exist.

- [ ] **Step 3: Implement raw-artifact-first orchestration**

`DocumentAdmissionService.admit_staged` validates context/request, publishes the owner-private staged regular file with media type `application/pdf`, verifies and registers the artifact through `ArtifactRepository`, builds a conservative `PDFSafetyProfile` from bounded streaming evidence plus Phase 1 disk/source policy, evaluates `PDFAdmissionPolicy`, then records the durable decision. Every structural/decompression/action signal not authoritatively available is `unknown`. Retry uses the same acquisition ID and content hash. Failures never delete CAS bytes; they raise typed errors without converting a missing durable record into success.

`DocumentIngestionServices.from_environment()` derives the exact `RuntimePaths`, socket-only `PostgresDatabase`, migration runner, artifact store/repository, acquisition repository, policy, and service from `RSI_ATLAS_DATA_ROOT`. Refactor shared environment construction rather than copying a second default-root rule.

- [ ] **Step 4: Implement bounded API streaming and direct CLI**

The API requires `Content-Type: application/pdf`, a decimal `Content-Length` in `1..33554432`, and UUID headers `X-RSI-Tenant-ID`, `X-RSI-Actor-ID`, `X-RSI-Trace-ID`, `X-RSI-Acquisition-ID`; it accepts a percent-decoded normalized filename query parameter, acquisition method, and collector version. Stream `request.stream()` into one random owner-private file below `<data-root>/staging/imports`, hash/count concurrently, enforce a second independent cap, `fsync`, and reject disconnects/length mismatch. Close and remove only that exact incomplete staging file on cancellation or failure. Never accept a filesystem path or URL.

CLI syntax:

```text
atlas import-pdf FILE --tenant-id UUID --workspace-id UUID --actor-id UUID --trace-id UUID --acquisition-id UUID --json
```

The CLI opens exactly one regular, non-symlink file using descriptor flags, checks owner-readable size before and after the bounded read, and emits the same JSON contract. Exit 0 means a durable decision was recorded, including quarantine/rejection; boundary or persistence failure exits nonzero with sanitized stderr.

- [ ] **Step 5: Prove zero egress and exact-root behavior**

Run the CLI and API admission commands against a disposable `RSI_ATLAS_DATA_ROOT` under the existing zero-egress verifier. Deny external TCP and mDNS, permit only the exact PostgreSQL Unix socket, and confirm the supervised engine environment contains the same root. Record artifact hash, acquisition ID, outcome, duplicate identity when present, socket/staging owner and modes, and process command.

- [ ] **Step 6: Run full Python verification and commit Task 4**

```bash
uv lock --check
uv run ruff check packages services infra
uv run ruff format --check packages services infra
uv run mypy packages services infra
RSI_ATLAS_TEST_DATABASE_URL="$(./infra/local/postgres.sh test-url)" uv run pytest -q
git add packages services pyproject.toml uv.lock
git commit -m "feat: admit immutable PDFs through local boundaries"
```

---

### Task 5: Native Evidence import and durable decision presentation

**Files:**
- Create: `apps/macos/Sources/RSIAtlasCore/Models/DocumentAdmission.swift`
- Create: `apps/macos/Sources/RSIAtlasCore/Services/DocumentImportClient.swift`
- Create: `apps/macos/Sources/RSIAtlasCore/Stores/DocumentImportStore.swift`
- Modify: `apps/macos/Sources/RSIAtlasApp/Models/WorkspaceDestination.swift`
- Modify: `apps/macos/Sources/RSIAtlasApp/Views/SidebarView.swift`
- Modify: `apps/macos/Sources/RSIAtlasApp/Views/ContentView.swift`
- Create: `apps/macos/Sources/RSIAtlasApp/Views/EvidenceImportView.swift`
- Create: `apps/macos/Tests/RSIAtlasCoreTests/DocumentAdmissionDecodingTests.swift`
- Create: `apps/macos/Tests/RSIAtlasCoreTests/DocumentImportStoreTests.swift`
- Create: `apps/macos/Tests/RSIAtlasCoreTests/DocumentImportClientTests.swift`
- Create: `apps/macos/Tests/RSIAtlasCoreTests/Fixtures/document_admission_v1.json`

**Interfaces:**
- Consumes: one security-scoped local PDF and the Task 4 endpoint.
- Produces: an Evidence workspace that visibly distinguishes awaiting-review, password, rejected, and exact-duplicate evidence without claiming admission, parsing, indexing, or publication.

- [ ] **Step 1: Write cross-language decoding and store RED tests**

```swift
@Test func admissionFixtureDecodesStrictly() throws {
    let record = try JSONDecoder.rsiAtlas.decode(DocumentAdmissionRecord.self, from: fixture)
    #expect(record.schemaVersion == "1.0.0")
    #expect(record.outcome == .quarantineForReview)
    #expect(record.lifecycle == .awaitingReview)
}


@Test func staleImportCannotReplaceLatestResult() async {
    let store = DocumentImportStore(client: client)
    async let first: Void = store.importPDF(firstURL)
    async let second: Void = store.importPDF(secondURL)
    await client.completeSecond(with: secondRecord)
    await client.completeFirst(with: firstRecord)
    _ = await (first, second)
    #expect(store.record == secondRecord)
}
```

- [ ] **Step 2: Run Swift tests and verify RED**

Run: `swift test --package-path apps/macos`

Expected: compilation fails because the admission models/client/store do not exist.

- [ ] **Step 3: Implement strict models, local identity, and transport**

Mirror every enum and field from the Python `DocumentAdmissionRecord`; decode with the existing recursively strict JSON boundary. `LocalWorkspaceIdentity` is explicitly development-scoped, generates tenant/workspace/actor UUIDs once in standard app preferences, and creates new trace/acquisition UUIDs per import. `DocumentImportClient` coordinates security-scoped access, rejects symlinks/non-PDF/zero/over-limit/change-during-read, uploads from the file URL with URLSession's file-backed upload API, caps response bytes, and maps HTTP/contract/transport/cancellation errors without exposing private full paths.

- [ ] **Step 4: Implement the truthful Evidence surface**

Add an `Evidence` sidebar destination and a native `fileImporter` restricted to `.pdf`. Present empty, uploading, awaiting-review, password, rejected, duplicate, and failed states. The result includes filename, lifecycle, outcome, raw artifact hash, duplicate target when present, safety check rows, reason rows, and exact copy that says `Quarantined — not admitted, parsed, or searchable`. Use text plus symbol plus semantic color; expose stable accessibility IDs for import button, progress, outcome, raw artifact, safety checks, reasons, and error/retry. Do not add drag-and-drop or watched folders in this slice.

- [ ] **Step 5: Verify native behavior and release cfg boundary**

Run:

```bash
swift test --package-path apps/macos
swift build --package-path apps/macos --product RSIAtlas
swift build -c release --package-path apps/macos --product RSIAtlas
```

In the foreground development app, import clean-looking, suspicious, encrypted, rejected-signature, and exact-duplicate fixtures; verify the clean-looking file remains awaiting review, plus same-window failure/retry, keyboard navigation, VoiceOver order, 860x600 content size, typical size, Light/Dark, large text, increased contrast, Reduce Motion, and a second window. Confirm no debug QA override changes release behavior.

- [ ] **Step 6: Commit Task 5**

```bash
git add apps/macos
git commit -m "feat: add native immutable PDF admission"
```

---

### Task 6: Phase 2A acceptance, recovery, and evidence closure

**Files:**
- Modify: `README.md`
- Modify: `docs/production-plan.md`
- Modify: `docs/acceptance-matrix.md`
- Modify: `docs/superpowers/plans/2026-07-18-full-product-delivery-roadmap.md`
- Create: `.superpowers/sdd/phase-2a-report.md` (ignored local evidence)

**Interfaces:**
- Consumes: Tasks 1–5 and the exact disposable runtime.
- Produces: a reviewed Phase 2A checkpoint and an explicit plan boundary for parser/preflight work.

- [ ] **Step 1: Run the all-up automated gate**

```bash
uv lock --check
uv run ruff check packages services infra
uv run ruff format --check packages services infra
uv run mypy packages services infra
RSI_ATLAS_TEST_DATABASE_URL="$(./infra/local/postgres.sh test-url)" uv run pytest -q
swift test --package-path apps/macos
swift build --package-path apps/macos --product RSIAtlas
swift build -c release --package-path apps/macos --product RSIAtlas
bash -n script/build_and_run.sh infra/local/postgres.sh
git diff --check
```

Expected: no warnings, skipped required integration tests, formatting drift, or contract mismatch.

- [ ] **Step 2: Run fault and restart smokes**

Use a disposable owner-private root. Kill the engine during request submission and verify the native app reports failure without a fabricated record or leftover staging file; retry with the same acquisition ID and file and obtain one durable decision. Stop PostgreSQL after raw artifact publication and before decision commit, restore it, retry, and confirm one acquisition plus retained raw bytes. Restart the full stack and verify the acquisition, decision, duplicate link, artifact bytes, actor, trace, safety profile, and reason evidence are unchanged.

- [ ] **Step 3: Run the security/adversarial matrix**

Exercise wrong MIME, oversized body, truncated stream, symlink CLI input, active actions, embedded file, encrypted marker, external reference, malformed header/trailer, unresolved page markers, traversal filename, cross-workspace duplicate isolation, acquisition-ID replay conflict, and concurrent duplicate imports. Confirm no parser, model, subprocess, DNS, external TCP, or mDNS access occurs.

- [ ] **Step 4: Reconcile the specification boundary**

Update the acceptance matrix with direct partial evidence for exact-duplicate handling in criterion 10 and boundary/history/offline portions of criteria 17, 19, 23, and 24 only. Keep new-version handling and criteria 11–16, 18, 20–22 explicitly unproven because promoted safety profiling, parsing, scanned fallback, canonical regions, five chunkers, indexes, publication, human interrupts, page citations, and benchmarks do not exist in Phase 2A.

- [ ] **Step 5: Broad independent review and remediation**

Request a spec-compliance review and a code-quality/security review over the exact Phase 2A commit range. Resolve every Critical or Important finding, rerun the smallest affected checks, then rerun the full gate. Record accepted review SHA(s), exact test counts, fixture hashes, runtime commands, and remaining boundary in `.superpowers/sdd/phase-2a-report.md`.

- [ ] **Step 6: Commit Phase 2A closure**

```bash
git add README.md docs
git commit -m "docs: close secure document admission slice"
```

Expected: Phase 2A is a truthful durable admission checkpoint, not a claim that document intelligence or any full ingestion acceptance criterion is complete.

---

## Verification

- `uv lock --check`
- `uv run ruff check packages services infra`
- `uv run ruff format --check packages services infra`
- `uv run mypy packages services infra`
- `RSI_ATLAS_TEST_DATABASE_URL="$(./infra/local/postgres.sh test-url)" uv run pytest -q`
- `swift test --package-path apps/macos`
- `swift build --package-path apps/macos --product RSIAtlas`
- `swift build -c release --package-path apps/macos --product RSIAtlas`
- `bash -n script/build_and_run.sh infra/local/postgres.sh`
- `git diff --check`
- Manual smoke: clean-looking-awaiting-review, password, suspicious, rejected, and duplicate native imports; engine/database interruption and idempotent retry; restart persistence; compact/appearance/accessibility/multi-window; and exact development zero-egress.

## Decision Log

- 2026-07-18: Split Phase 2 into admission, parsing/canonicalization, chunking/evaluation, and index-publication plans because each subsystem has a distinct promotion and rollback gate.
- 2026-07-18: Make raw immutable storage precede policy evaluation; a rejected or review-required artifact remains inspectable evidence.
- 2026-07-18: Phase 2A can only quarantine/review, request a password, reject, or link an exact duplicate. A deterministic scanner cannot prove all mandatory PDF safety checks, so even an apparently clean file cannot become admitted.
- 2026-07-18: Defer new-version registration until an authoritative safety profiler and document-series contract exist; filename similarity cannot silently merge evidence lineage.
- 2026-07-18: Stream through an owner-private staging file and file-backed native upload; neither app nor engine buffers the full PDF.
- 2026-07-18: Use raw bounded HTTP request bytes for the current local API so the engine never receives an arbitrary filesystem path and no multipart dependency is added.
- 2026-07-18: Keep all acquisition outcomes durable and return success only for a recorded decision; quarantine/rejection is evidence, while transport/persistence failure is not.

## Progress Log

- 2026-07-18: Completed: approved §§12–15, acceptance criteria 10–24, Appendix D, current Phase 1 storage/runtime seams, and PDF tooling constraints reviewed.
- 2026-07-18: Current: Task 1 strict acquisition/admission contract RED.
- 2026-07-18: Next: implement Tasks 1–6 sequentially with independent review gates, then write the Phase 2B parser/preflight/canonicalization plan.

## Rollback / Recovery

- If this fails: stop only exact disposable engine/database/app processes; preserve immutable raw artifacts, append-only acquisition evidence, test fixtures, and committed Phase 1 behavior; repair forward without resetting user work.
- Safe fallback: retain the last independently reviewed task commit, disable the Evidence destination or admission route at composition, and leave stored raw artifacts quarantined and unreachable from retrieval.
