# Phase 2B Governed Parser, Preflight, and Canonical Pages Implementation Plan

> **Execution:** Follow the repository TDD and review gates task by task. Do not begin Phase 2C
> chunking until every Phase 2B acceptance item below is either proven or explicitly left unpromoted.

**Goal:** Turn an immutable Phase 2A PDF artifact into a versioned, reviewable preflight assessment
and canonical page/layout artifact without weakening raw-byte lineage, zero-egress, or the rule that
partial content is never searchable.

**User-visible outcome:** From the native development Evidence workspace, an analyst can run bounded preflight
and parsing on a supported born-digital PDF, inspect page-by-page canonical text and source
coordinates, see quality warnings or a review-required outcome, and confirm that scanned,
encrypted, unsafe, or low-quality documents remain unparsed/unpublished.

**Architecture:** Keep the initial Phase 2A admission record immutable. Phase 2B adds append-only
admission assessments and parser runs linked to the exact raw artifact, acquisition, workspace,
actor, trace, profiler/parser build, configuration hash, and run identity. Untrusted PDF libraries
run only in a separately invoked document-worker process with one read-only artifact, one
owner-private run directory, no network or secrets, bounded time/memory/output, and a strict
request/response contract. On macOS development builds the worker additionally runs under an
OS-enforced deny-by-default Seatbelt profile. Phase 2B cannot claim release-grade parser isolation
or production promotion until the later signed sandboxed helper/XPC gate passes. Canonical JSON is
published to CAS before its manifest is committed.

**Initial governed candidates:**

- `pypdf==6.14.2` for strict structural preflight and a simple text baseline. PyPI identifies the
  current release as BSD-3-Clause, typed, and production/stable; its reader exposes encryption and
  attachment evidence: <https://pypi.org/project/pypdf/6.14.2/> and
  <https://pypdf.readthedocs.io/en/latest/modules/PdfReader.html>.
- `pdfminer.six==20260107` for Tier-0 page/layout text spans. Its official API yields `LTPage`
  layout objects, and the current release includes the post-CVE JSON CMap change:
  <https://pdfminersix.readthedocs.io/en/master/reference/highlevel.html> and
  <https://pypi.org/project/pdfminer.six/>.
- `docling==2.113.0` remains the required Tier-1 benchmark candidate, not an automatic production
  dependency. Its standard pipeline can run locally, while OCR/layout/table models and their
  licenses/artifacts must be pinned and available offline before promotion:
  <https://pypi.org/project/docling/> and
  <https://docling-project.github.io/docling/examples/agent_skill/docling-document-intelligence/pipelines/>.

**Phase boundary:** Phase 2B does not chunk, embed, index, publish to retrieval, run OCR/VLM repair,
or claim scanned-PDF support. It may route image-only/low-quality/ambiguous pages to review and
record why. Phase 2C owns five chunking families and frozen chunk benchmarks. Phase 2D owns dense
and lexical indexes plus atomic retrieval publication.

---

## Contract and safety invariants

1. Phase 2A `DocumentAdmissionRecord` rows and raw CAS bytes are never updated or replaced.
2. A Phase 2B assessment is a new append-only fact. It names the prior admission, exact artifact,
   profiler identity/configuration, evidence, decision, actor, trace, and time.
3. Only a promoted profiler record may emit `accept` or `accept_with_restrictions`. Candidate runs
   may recommend; they cannot promote themselves.
4. Parser input is one verified CAS payload opened read-only by the engine. The worker never
   receives a user-selected path, database URL, credential, network authority, or writable CAS root.
5. Candidate output is untrusted until strict schema validation, raw-hash binding, page/cardinality
   bounds, coordinate validation, text/control validation, quality scoring, and crypto-token
   preservation checks pass in the engine process.
6. Canonical coordinates use normalized top-left page space in `[0, 1]`; raw parser coordinates and
   the declared source coordinate system are retained for audit.
7. Canonical element IDs are deterministic from document version, page, element kind, reading
   order, normalized box, and raw-text hash. Rerunning identical inputs/configuration yields the same
   canonical bytes and hash.
8. Raw and normalized text are both retained. Normalization is Unicode NFC plus explicitly tested
   whitespace/hyphenation rules; it never silently rewrites numbers, addresses, symbols, dates, or
   code identifiers.
9. A document remains non-searchable throughout Phase 2B. No table named or API described as a
   production index may consume canonical elements yet.
10. Every failure is typed and sanitized; worker stderr, private paths, PDF bytes, and extracted text
    never enter logs or HTTP error responses.
11. Every parser/preflight attempt has an append-only `started` event before child execution and one
    append-only terminal event after success, failure, cancellation, timeout, kill, invalid output,
    disagreement, review, or fallback. Startup reconciliation closes abandoned attempts without
    deleting their immutable output evidence.
12. A dependency or model artifact cannot enter the workspace lock or a qualification record until
    its full transitive inventory, hashes, provenance, SPDX/license status, advisories, unsafe-load/
    remote-code behavior, SBOM delta, and explicit dependency approval are recorded.

---

### Task 1: Versioned preflight, parser-run, quality, and canonical contracts

**Files:**

- Create: `packages/contracts/src/rsi_atlas_contracts/document_parsing.py`
- Modify: `packages/contracts/src/rsi_atlas_contracts/acquisition.py`
- Modify: `packages/contracts/src/rsi_atlas_contracts/__init__.py`
- Create: `packages/contracts/tests/test_document_parsing.py`
- Create: `packages/contracts/tests/fixtures/document_preflight_v1.json`
- Create: `packages/contracts/tests/fixtures/canonical_document_v1.json`

**Interfaces:**

- `DocumentProfilerIdentity`, `DocumentPreflightProfile`, `AdmissionAssessment`
- `ParserCandidateIdentity`, `ParserRunRequest`, `ParserRunResult`, `ParserQualityReport`
- `CoordinateSystem`, `BoundingBox`, `CanonicalElement`, `CanonicalPage`, `CanonicalDocument`
- `DocumentProcessingLifecycle` with `preflighted`, `parsing`, `parse_validated`, `canonicalized`,
  `awaiting_review`, `failed_retryable`, and `failed_terminal`; no searchable/published state.

- [ ] **Step 1: Write strict RED contract tests**

Cover unknown fields at every nested boundary, exact schema versions, UTC timestamps, controlled
IDs, NFC/control rejection, finite normalized coordinates, positive page dimensions, page/order
uniqueness, deterministic element IDs, raw/normalized text hashes, raw artifact binding, profiler
promotion identity, lifecycle/decision consistency, warning/reason ordering, and bounded counts.

- [ ] **Step 2: Run RED**

```bash
uv run pytest packages/contracts/tests/test_document_parsing.py -q
```

Expected: import/collection failure because the contracts do not exist.

- [ ] **Step 3: Implement the smallest strict models**

Use Pydantic strict mode, forbidden extras, discriminated element unions, decimal/finite coordinate
validation, and deterministic JSON encoding. Extend admission policy versions without weakening the
existing `phase-2a-1` decoder or allowing a Phase 2A service to emit promoted outcomes.

- [ ] **Step 4: Add cross-representation invariant tests**

Reject an assessment bound to another artifact/acquisition/workspace, canonical pages omitted or
duplicated, text hashes that do not match content, coordinates outside page bounds, a quality report
for another parser run, and a canonical document whose element lineage does not name its source run.

- [ ] **Step 5: Verify and commit Task 1**

```bash
uv run pytest packages/contracts/tests -q
uv run ruff check packages/contracts
uv run ruff format --check packages/contracts
uv run mypy packages/contracts/src
git add packages/contracts
git commit -m "feat: define canonical document contracts"
```

---

### Task 2: Frozen crypto PDF corpus and deterministic benchmark contract

**Files:**

- Create: `packages/ingestion/benchmarks/pdf/manifest.json`
- Create: `packages/ingestion/benchmarks/pdf/golden/*.json`
- Create: `packages/ingestion/benchmarks/pdf/fixtures/*.pdf`
- Create: `packages/ingestion/benchmarks/pdf/README.md`
- Create: `packages/ingestion/tests/test_pdf_benchmark_corpus.py`
- Create: `script/build_pdf_benchmark_fixtures.py`

**Corpus partitions:**

- `development`: synthetic minimal and edge fixtures used while building adapters;
- `calibration`: labelled representative PDFs used to freeze thresholds without changing code;
- `validation`: licensed representative PDFs visible to implementation writers and used only after
  development/calibration thresholds are frozen; this partition can support development
  qualification but cannot support production promotion;
- `adversarial`: malicious, malformed, resource-boundary, and parser-disagreement fixtures.

Declared born-digital support must include licensed examples across whitepaper, technical paper,
audit, governance, tokenomics, legal/regulatory disclosure, and market-report families, with
single-column, multi-column, table, figure/caption, rotated/crop-box, long-document, and mixed-font
layouts. Development fixtures also include a three-page crypto technical paper with headings, two columns, footers, EVM/Solana/Bitcoin IDs,
  percentages, dates, symbols, and a simple token-allocation table;
- rotated/crop-box page;
- image-only page that must route to review without OCR;
- encrypted/password-required PDF;
- attachment, JavaScript/action, URI, malformed xref/trailer, decompression-boundary, and over-page
  fixtures;
- parser-disagreement fixture with an explicitly labelled expected review outcome.

- [ ] **Step 1: Write corpus integrity RED tests**

Require SHA-256, license/provenance, expected page count, expected raw strings and bounding regions,
expected preflight route, maximum fixture size, and no hidden network/resource locator. Fixture
generation must be deterministic or the committed manifest must pin exact generated bytes.

- [ ] **Step 2: Build and visually inspect fixtures**

Use the repository script and bundled PDF render tooling. Render every page, inspect for clipping,
reading-order intent, fonts, table geometry, and image-only truth. Keep screenshots under ignored
evidence paths; commit PDFs, goldens, generator, and hashes only.

- [ ] **Step 3: Implement the benchmark manifest contract**

The manifest freezes partition, license/provenance, candidate/version/configuration, fixture hash,
expected page/text/region/token evidence, required-pass metrics, and qualification status. Performance
uses at least 3 warm-up iterations plus 30 measured cold-process and 30 measured warm-process runs
per declared size class on named reference hardware; denominators, p50/p95, peak RSS, timeout count,
and failures are recorded. A missing candidate is `unavailable`, never silently skipped or scored as
passing.

- [ ] **Step 4: Verify and commit Task 2**

```bash
uv run pytest packages/ingestion/tests/test_pdf_benchmark_corpus.py -q
uv run ruff check packages/ingestion script/build_pdf_benchmark_fixtures.py
uv run ruff format --check packages/ingestion script/build_pdf_benchmark_fixtures.py
git diff --check
git add packages/ingestion/benchmarks packages/ingestion/tests/test_pdf_benchmark_corpus.py script/build_pdf_benchmark_fixtures.py
git commit -m "test: freeze crypto PDF parser corpus"
```

---

### Task 3: Parser dependency and artifact governance gate

**Files:**

- Create: `docs/dependency-governance/pdf-parser-candidates.json`
- Create: `docs/dependency-governance/pdf-parser-approval.md`
- Create: `script/audit_pdf_parser_dependencies.py`
- Create: `tests/test_pdf_parser_dependency_governance.py`
- Create: `.superpowers/sdd/phase-2b-sbom.json` (ignored evidence)

- [ ] **Step 1: Write governance RED tests**

Require every direct/transitive wheel and model/config artifact to name version, source URL,
SHA-256, package identity, SPDX expression or reviewed license reference, platform/Python tags,
publisher/attestation when available, advisory snapshot/time, and whether import/load can execute
remote code, deserialize unsafe formats, fetch URLs, or dynamically load native code.

- [ ] **Step 2: Resolve candidates outside the accepted workspace lock**

Generate a scratch lock and full dependency graph for pypdf, pdfminer.six, and Docling without
merging it. Download wheels/model artifacts only into an ignored owner-private review cache; verify
hashes and provenance. Inspect install hooks, entry points, native libraries, dynamic downloads,
unsafe serialization, remote-code flags, licenses, and platform compatibility.

- [ ] **Step 3: Produce the SBOM/advisory delta**

Record direct and transitive components, hashes, licenses, known advisories, severity/mitigation,
and the exact delta from the accepted `uv.lock`. Advisory tooling and its database/snapshot are
themselves pinned and identified. Any unknown license, unreviewed model artifact, critical/high
unmitigated advisory, runtime download, or arbitrary-code load blocks installation/promotion.

- [ ] **Step 4: Obtain and record explicit dependency approval**

The approval names exactly which candidates may enter `pyproject.toml`/`uv.lock`, permitted extras,
accepted advisory/license exceptions, model artifacts, and rollback. No approval is inferred from
the product spec. Unapproved candidates remain `blocked:dependency_governance`.

- [ ] **Step 5: Verify and commit Task 3**

```bash
uv run pytest tests/test_pdf_parser_dependency_governance.py -q
uv run ruff check script/audit_pdf_parser_dependencies.py tests
uv run ruff format --check script/audit_pdf_parser_dependencies.py tests
git diff --check
git add docs/dependency-governance script/audit_pdf_parser_dependencies.py tests/test_pdf_parser_dependency_governance.py
git commit -m "docs: govern PDF parser dependencies"
```

---

### Task 4: OS-enforced document-worker protocol and bounded runner

**Files:**

- Create: `packages/document_worker/pyproject.toml`
- Create: `packages/document_worker/src/rsi_atlas_document_worker/__init__.py`
- Create: `packages/document_worker/src/rsi_atlas_document_worker/protocol.py`
- Create: `packages/document_worker/src/rsi_atlas_document_worker/worker.py`
- Create: `packages/document_worker/tests/test_worker_protocol.py`
- Create: `packages/ingestion/src/rsi_atlas_ingestion/worker_runner.py`
- Create: `packages/ingestion/tests/test_worker_runner.py`
- Create: `infra/security/document-worker.sb`
- Create: `infra/security/tests/test_document_worker_sandbox.py`
- Modify: `pyproject.toml`
- Modify: `uv.lock`

**Boundary:** The engine opens the verified CAS payload and a fresh owner-private run directory,
passes only explicit file descriptors, sends one bounded JSON request, and accepts one bounded JSON
response plus declared output artifacts. The child starts in its own process group, with a scrubbed
environment, no inherited descriptors beyond the allowlist, CPU/address-space/file-size/process
limits, timeout/cancel kill escalation, and the document-worker offline capability profile. The
runner must fail closed unless `/usr/bin/sandbox-exec` successfully applies the reviewed Seatbelt
profile. That profile defaults to deny and grants only the exact Python/runtime/library reads,
read-only input descriptor, run-directory writes, and minimal system services required to start;
it denies network, arbitrary user files, Keychain/security services, process fork/exec, and child
escape. This is development evidence only because `sandbox-exec` is not the release isolation gate.

- [ ] **Step 1: Write runner RED tests**

Cover exact request/response schema, descriptor allowlist, environment removal, sandbox-unavailable/
profile-failure refusal, timeout, SIGKILL,
cancellation, oversized stdout/stderr/output files, malformed JSON, exit/signal mapping, path
traversal, symlink output, wrong file identity, partial-file cleanup, and sanitized failures.

- [ ] **Step 2: Implement an echo/hash worker first**

The first green worker only verifies descriptor bytes/digest/size and returns its build/capability
identity. It must not import a PDF library yet. Run in-sandbox canaries that attempt DNS, external
TCP, mDNS, arbitrary user-file reads, Keychain lookup, Mach service access, fork, exec, descendant
escape, database access, model access, and writes outside the run directory; every attempt must be
denied by the OS boundary rather than by worker cooperation.

- [ ] **Step 3: Prove hard-kill and concurrent-run recovery**

Kill the worker after partial output, restart the runner, and show safe cleanup plus stable retry
identity. Run two workspaces concurrently and prove run-directory and artifact isolation.

- [ ] **Step 4: Verify and commit Task 4**

```bash
uv lock --check
uv run pytest packages/document_worker packages/ingestion/tests/test_worker_runner.py infra/security/tests/test_document_worker_sandbox.py -q
uv run ruff check packages/document_worker packages/ingestion
uv run ruff format --check packages/document_worker packages/ingestion
uv run mypy packages/document_worker/src packages/ingestion/src
git diff --check
git add pyproject.toml uv.lock packages/document_worker packages/ingestion infra/security/document-worker.sb infra/security/tests/test_document_worker_sandbox.py
git commit -m "feat: add isolated document worker"
```

---

### Task 5: Authoritative preflight, attempt history, and admission reassessment

**Files:**

- Create: `packages/document_worker/src/rsi_atlas_document_worker/preflight.py`
- Create: `packages/document_worker/tests/test_preflight.py`
- Create: `packages/ingestion/src/rsi_atlas_ingestion/preflight_service.py`
- Create: `packages/ingestion/tests/test_preflight_service.py`
- Create: `migrations/0004_document_preflight.sql`
- Create: `packages/storage/src/rsi_atlas_storage/document_processing_repository.py`
- Create: `packages/storage/tests/test_document_processing_repository.py`
- Modify: package exports and pinned dependencies/lock.

**Preflight evidence:** exact page count and geometry; encryption/password state; attachment/name-tree
evidence; catalog/open/additional actions and JavaScript; URI/launch/remote-go-to references;
strict-parse/malformed evidence; compressed and decoded stream accounting with hard limits; per-page
character counts; extractability/image-only ratios; font/encoding anomaly counts; probable language
as `unknown` until a governed deterministic detector exists; multi-column/table/figure/math/header-
footer/family signals as bounded heuristics with confidence and `unknown` support.

- [ ] **Step 1: Write RED preflight and persistence tests**

Require an append-only started event before every profiler worker invocation and an append-only
terminal event for success/failure/timeout/kill/cancel/invalid output. Reconciliation closes a
started-without-terminal attempt after engine death. Require all mandatory safety checks to be authoritative before a promoted assessment can accept.
Unsafe/encrypted/unknown/limit cases route to reject, password, or review. Reassessment is append-only;
initial Phase 2A evidence remains byte-for-byte unchanged. Exact replay is idempotent; divergent
reuse conflicts; cross-workspace reads and profiler identities fail.

The migration and repository establish the generic acquisition-bound attempt journal used by both
preflight and parser work: append-only `document_parser_attempt_events` rows, immutable attempt
identity and input/configuration bindings, `start_attempt`, `finish_attempt`, and
`reconcile_abandoned` operations, and a database constraint preventing more than one terminal event
per attempt. Benchmark executions are separate evaluation records and never stand in for this
runtime processing history.

- [ ] **Step 2: Add pinned `pypdf` worker dependency and implement bounded preflight**

Use strict parsing, explicit recursion/object/stream/page limits, and never extract attachments or
follow references. Catch library exceptions only at the adapter boundary and return typed evidence.
The engine independently binds every result to raw artifact/acquisition/run/configuration hashes.

- [ ] **Step 3: Implement promotion records**

Promotion is a committed, versioned policy artifact tied to the frozen benchmark. Without that
record the candidate can produce evidence but the assessment must remain `awaiting_review`.

- [ ] **Step 4: Run real PostgreSQL and adversarial recovery tests**

Inject failure after CAS/preflight output and before assessment commit; retry must reuse immutable
outputs and create one assessment/outbox event. Kill worker and database at each durable boundary.

- [ ] **Step 5: Verify and commit Task 5**

```bash
RSI_ATLAS_TEST_DATABASE_URL="$(./infra/local/postgres.sh test-url)" uv run pytest packages/document_worker/tests/test_preflight.py packages/ingestion/tests/test_preflight_service.py packages/storage/tests/test_document_processing_repository.py -q
uv run ruff check packages services
uv run ruff format --check packages services
uv run mypy packages services
git add pyproject.toml uv.lock migrations packages/document_worker packages/ingestion packages/storage
git commit -m "feat: add governed PDF preflight"
```

---

### Task 6: Tier-0 parser candidates, benchmark, and qualification gate

**Files:**

- Create: `packages/document_worker/src/rsi_atlas_document_worker/parsers/base.py`
- Create: `packages/document_worker/src/rsi_atlas_document_worker/parsers/pypdf_adapter.py`
- Create: `packages/document_worker/src/rsi_atlas_document_worker/parsers/pdfminer_adapter.py`
- Create: `packages/document_worker/src/rsi_atlas_document_worker/parsers/docling_adapter.py`
- Create: `packages/document_worker/tests/test_parser_candidates.py`
- Create: `packages/ingestion/src/rsi_atlas_ingestion/parser_benchmark.py`
- Create: `packages/ingestion/tests/test_parser_benchmark.py`
- Create: `packages/ingestion/src/rsi_atlas_ingestion/parser_service.py`
- Create: `packages/ingestion/tests/test_parser_service.py`
- Create: `.superpowers/sdd/phase-2b-parser-benchmark.json` (ignored evidence)
- Extend: `packages/storage/src/rsi_atlas_storage/document_processing_repository.py`
- Extend: `packages/storage/tests/test_document_processing_repository.py`
- Modify: pinned dependencies and `uv.lock`.

- [ ] **Step 1: Write candidate RED tests against the frozen corpus**

Every candidate returns page geometry, ordered text spans, font/encoding evidence where supported,
links, images/counts where supported, candidate warnings, and exact source coordinates. Unsupported
evidence is explicit, not fabricated.

- [ ] **Step 2: Implement pypdf and pdfminer candidates**

Normalize only into the candidate schema. Do not construct canonical elements inside adapters.
Limit pages, objects, decoded bytes, spans, text bytes, images, recursion, runtime, and output size.

- [ ] **Step 3: Exercise Docling as an evaluation-only candidate**

Pin `docling==2.113.0` and every required local model artifact/configuration hash in the benchmark
record. Run with URL input disabled, remote services disabled, offline environment enforced, and
only the frozen corpus. If model artifacts/licenses are unavailable or the dependency requires
runtime egress, record `blocked:unqualified_artifact` and do not promote or substitute another
structure-aware parser silently.

- [ ] **Step 4: Score deterministic quality metrics**

Measure page coverage, exact expected strings, bounding-region overlap, reading order, replacement
characters, numeric/address/date/symbol preservation, duplicated/missing blocks, table header/cell
coverage, runtime, peak RSS, output size, and deterministic rerun hash. Required fixture failures or
unavailable required evidence block promotion.

- [ ] **Step 5: Persist every attempt and freeze the development qualification record**

For every acquisition-bound parser launch, `parser_service` persists `started` through the generic
attempt journal; after any terminal path it persists exact status, resource evidence, warnings,
validated output artifact hash when present, and fallback/review reason. Real-PostgreSQL crash tests
kill execution after the start event and before the terminal event, then prove
`reconcile_abandoned` closes the attempt exactly once and a safe retry remains separately auditable.
The accepted canonical manifest later references this retained run rather than recreating it.
Benchmark launches write benchmark evaluation records only and do not create or impersonate
acquisition-bound attempt history.

Qualify at most one Tier-0 development candidate for straightforward born-digital pages. Image-only,
parser disagreement, failed crypto invariants, unsupported tables, or low coverage route to review.
Docling/Tier-1 promotion is independent and may remain blocked without preventing honest Tier-0
canonicalization. No candidate is production-promoted until an independently controlled sealed
holdout unavailable to implementation writers, dependency approval, and release signed-helper
isolation gates all pass.

- [ ] **Step 6: Verify and commit Task 6**

```bash
RSI_ATLAS_TEST_DATABASE_URL="$(./infra/local/postgres.sh test-url)" uv run pytest packages/document_worker/tests/test_parser_candidates.py packages/ingestion/tests/test_parser_benchmark.py packages/ingestion/tests/test_parser_service.py packages/storage/tests/test_document_processing_repository.py -q
uv run ruff check packages/document_worker packages/ingestion
uv run ruff format --check packages/document_worker packages/ingestion
uv run mypy packages/document_worker/src packages/ingestion/src packages/storage/src
git add pyproject.toml uv.lock packages/document_worker packages/ingestion packages/storage
git commit -m "feat: benchmark local PDF parser candidates"
```

---

### Task 7: Deterministic canonicalization and append-only persistence

**Files:**

- Create: `packages/ingestion/src/rsi_atlas_ingestion/canonicalization.py`
- Create: `packages/ingestion/tests/test_canonicalization.py`
- Create: `migrations/0005_canonical_documents.sql`
- Extend: `packages/storage/src/rsi_atlas_storage/document_processing_repository.py`
- Extend: `packages/storage/tests/test_document_processing_repository.py`

- [ ] **Step 1: Write canonicalization RED tests**

Cover stable IDs, page/order preservation, coordinate conversion for rotations/crop boxes, heading
tree bounds, repeated header/footer marking, paragraph reconstruction, conservative hyphen repair,
NFC, raw text retention, table/figure/caption relationships where candidate evidence exists,
language/family `unknown`, crypto/numeric preservation, byte-deterministic reruns, and fail-closed
quality thresholds.

- [ ] **Step 2: Implement pure canonicalization**

Keep candidate adapters and persistence out of the pure transform. Never infer missing text or
coordinates. Generated metadata is labelled separately. Unsupported structures remain warnings or
review requirements.

- [ ] **Step 3: Publish canonical JSON to CAS then commit one manifest**

Persist canonical bytes as a new media type, verify them from CAS, then atomically record the
canonical version, reference to an already-retained accepted parser attempt, quality report,
lifecycle event, and outbox event. Failure before
manifest commit leaves reusable immutable bytes but no visible canonical version.

- [ ] **Step 4: Prove idempotency, history, corruption, and restart**

Exact replay returns the same canonical version. Parser/config change creates a new version and
never overwrites the old. Corrupt/missing canonical bytes fail retrieval. Restart preserves every
raw/candidate/quality/canonical hash and relationship.

- [ ] **Step 5: Verify and commit Task 7**

```bash
RSI_ATLAS_TEST_DATABASE_URL="$(./infra/local/postgres.sh test-url)" uv run pytest packages/ingestion/tests/test_canonicalization.py packages/storage/tests/test_document_processing_repository.py -q
uv run ruff check packages/ingestion packages/storage
uv run ruff format --check packages/ingestion packages/storage
uv run mypy packages/ingestion/src packages/storage/src
git add migrations packages/ingestion packages/storage
git commit -m "feat: persist canonical PDF pages"
```

---

### Task 8: Processing API and native canonical-page Evidence Inspector

**Files:**

- Modify: `services/engine/src/rsi_atlas_engine/api.py`
- Modify: `services/engine/src/rsi_atlas_engine/ingestion.py`
- Create: `services/engine/tests/test_document_processing_api.py`
- Create: `apps/macos/Sources/RSIAtlasCore/Models/CanonicalDocument.swift`
- Create: `apps/macos/Sources/RSIAtlasCore/Services/DocumentProcessingClient.swift`
- Create: `apps/macos/Sources/RSIAtlasCore/Stores/DocumentProcessingStore.swift`
- Modify: `apps/macos/Sources/RSIAtlasApp/Views/EvidenceImportView.swift`
- Create: `apps/macos/Sources/RSIAtlasApp/Views/CanonicalPageEvidenceView.swift`
- Add focused Python and Swift tests/fixtures.

**API:** Start/retry one processing run by acquisition ID; fetch processing status; fetch one bounded
canonical page by canonical version/page number. Every route is workspace-scoped and loopback-only,
returns strict contracts, and never accepts or returns arbitrary filesystem paths.

- [ ] **Step 1: Write API/store/presentation RED tests**

Cover accepted/review/failed/retry states, latest-run wins, cancellation, response caps, page bounds,
wrong workspace, unavailable/corrupt canonical bytes, exact retry identity, and no premature
searchable/published language.

- [ ] **Step 2: Implement processing composition and native client/store**

Long work runs off the request event loop through the bounded worker runner. The app preserves the
Phase 2A admission record while showing distinct preflight/parser/canonical state and warnings.

- [ ] **Step 3: Implement canonical page inspection**

Show page selector, raw/normalized text toggle, element kind/order, parser identity, source box,
quality/warnings, and exact raw/canonical hashes. A lightweight overlay may render normalized boxes;
it must not display generated text as source content.

- [ ] **Step 4: Foreground verification**

Run supported born-digital, rotated, table, image-only, encrypted, unsafe, disagreement, worker
failure/retry, and exact replay fixtures. Verify keyboard/VoiceOver order, compact/typical windows,
Light/Dark, large text, increased contrast, Reduce Motion, multiple windows, and release cfg.

- [ ] **Step 5: Verify and commit Task 8**

```bash
RSI_ATLAS_TEST_DATABASE_URL="$(./infra/local/postgres.sh test-url)" uv run pytest services/engine/tests/test_document_processing_api.py -q
swift test --package-path apps/macos
swift build --package-path apps/macos --product RSIAtlas
swift build -c release --package-path apps/macos --product RSIAtlas
git diff --check
git add services/engine apps/macos
git commit -m "feat: inspect canonical PDF evidence"
```

---

### Task 9: Phase 2B acceptance and boundary closure

**Files:**

- Modify: `README.md`
- Modify: `docs/production-plan.md`
- Modify: `docs/acceptance-matrix.md`
- Modify: `docs/superpowers/plans/2026-07-18-full-product-delivery-roadmap.md`
- Create: `.superpowers/sdd/phase-2b-report.md` (ignored evidence)

- [ ] **Step 1: Run the all-up gate**

```bash
uv lock --check
uv run ruff check packages services infra script
uv run ruff format --check packages services infra script
uv run mypy packages services infra
uv run pytest tests/test_pdf_parser_dependency_governance.py infra/security/tests/test_document_worker_sandbox.py -q
RSI_ATLAS_TEST_DATABASE_URL="$(./infra/local/postgres.sh test-url)" uv run pytest -q
swift test --package-path apps/macos
swift build --package-path apps/macos --product RSIAtlas
swift build -c release --package-path apps/macos --product RSIAtlas
bash -n script/build_and_run.sh infra/local/postgres.sh
./script/build_and_run.sh --verify
git diff --check
```

- [ ] **Step 2: Run fault, resource, and zero-egress matrices**

Kill worker at request/read/candidate/output/CAS/DB boundaries; retry and verify retained started and
terminal attempt evidence, one visible accepted run, and no unsafe residue. Exercise time, RSS,
decoded-byte, page, span, output, disk, and cancellation limits. Record child descriptors/environment/
process tree plus OS-enforced arbitrary-file/Keychain/fork/exec/descendant/network denial.

- [ ] **Step 3: Run parser/canonical acceptance corpus**

Prove exact supported born-digital pages and coordinates across development/calibration/validation/
adversarial partitions, crypto/numeric preservation, deterministic
rerun hashes, image-only/encrypted/unsafe/review routes, parser disagreement, corruption detection,
history across parser/config changes, raw/canonical restart persistence, and the frozen warm/cold
performance protocol.

- [ ] **Step 4: Reconcile acceptance claims**

Update criteria 10–13, 17, 19, 23, and 24 only to the degree directly proven. Keep scanned/OCR,
five chunkers, parent-child/table production chunking, indexes/publication, human LangGraph
interrupts, citations, and benchmark-complete document intelligence unproven when absent.

- [ ] **Step 5: Broad independent review and remediation**

Request spec-compliance plus code-quality/security review over the exact Phase 2B range. Resolve all
Critical/Important findings and rerun affected plus full gates. Record accepted SHAs, candidate and
artifact versions/hashes/licenses, fixture hashes, metrics, test counts, runtime commands, and
remaining boundaries in the ignored Phase 2B report. Re-run dependency manifest/SBOM/advisory
verification against the final lock and fail if it differs from the explicit approval.

- [ ] **Step 6: Commit Phase 2B closure**

```bash
git add README.md docs
git commit -m "docs: close canonical PDF evidence slice"
```

---

## Development qualification thresholds

The initial Tier-0 candidate may be development-qualified only if all required born-digital
development, calibration, and validation fixtures pass:

- 100% pages represented exactly once;
- 100% required crypto identifiers, dates, percentages, currencies, symbols, and finding IDs
  preserved in raw and canonical text;
- zero non-finite/out-of-range boxes and zero source-hash mismatches;
- zero missing required final pages;
- replacement-character rate at or below the frozen fixture threshold;
- deterministic candidate, quality, and canonical hashes across three runs;
- no network/subprocess/model access from the worker beyond its own already-started process;
- no required-fixture timeout, RSS/file/output-limit breach, or unlabelled omission;
- p95 latency and peak RSS within the frozen reference-hardware ceiling.

This does not equal production promotion. Production remains blocked until release-grade signed
helper/XPC isolation, exact release artifact zero-egress, final SBOM/advisory review, and an
independently controlled sealed holdout unavailable to implementation writers passes on supported
reference hardware after code, configuration, and threshold hashes are frozen.

Failure on image-only, complex-table, or disagreement fixtures is acceptable only when the result is
an explicit review/fallback route and no canonical version is exposed as production-ready.

## Decision log

- 2026-07-19: Keep Phase 2A admission immutable; Phase 2B adds append-only reassessment and
  processing history rather than updating the first decision.
- 2026-07-19: Evaluate pypdf/pdfminer as bounded Tier-0 candidates and Docling as the specified
  Tier-1 candidate. No library is selected solely because it is already installed.
- 2026-07-19: Treat parser dependencies and model artifacts as an explicit approval gate with full
  transitive governance; product-spec approval alone does not authorize a specific dependency set.
- 2026-07-19: Use Seatbelt only for development qualification. Release production promotion remains
  blocked on the signed sandboxed worker/XPC boundary in Phase 6.
- 2026-07-19: OCR and VLM repair remain outside Phase 2B. Image-only pages must route to review until
  a separate frozen OCR benchmark, artifact/license record, and resource gate pass.
- 2026-07-19: Canonical JSON becomes immutable evidence but remains unavailable to retrieval until
  Phase 2D atomically publishes validated indexes.

## Rollback / recovery

- Disable processing composition while retaining Phase 2A native/CLI admission and all immutable
  raw evidence.
- Preserve candidate, quality, promotion, and canonical artifacts for audit; never delete them to
  conceal a failed promotion.
- A failed migration or worker rollout repairs forward. Do not mutate or truncate append-only Phase
  2A/2B tables.
- If Docling or its model artifacts cannot pass licensing, offline, resource, or benchmark gates,
  leave Tier-1 blocked and continue only with honestly scoped Tier-0 support.
