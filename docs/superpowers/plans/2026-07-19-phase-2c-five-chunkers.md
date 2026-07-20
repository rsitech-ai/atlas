# Phase 2C Five Chunking Families Implementation Plan

> **Execution:** Follow repository TDD and review gates task by task. Do not begin Phase 2D
> embedding/index publication until every Phase 2C acceptance item below is either proven or
> explicitly left as development-only.

**Goal:** Turn a Phase 2B canonical document into versioned, inspectable `ChunkSet` projections
across five implemented chunking families, with frozen intrinsic benchmarks and exact source
lineage, without making content searchable or writing retrieval indexes.

**User-visible outcome:** From development Evidence/processing surfaces, an analyst can run
chunking against a canonical document version, inspect chunk text and source element lineage for
each of five families, and confirm that chunk sets remain non-searchable evidence only.

**Architecture:** Keep Phase 2A admissions and Phase 2B canonical versions immutable. Phase 2C adds
pure deterministic chunkers over canonical element streams, append-only `ChunkSet` manifests bound
to exact canonical content hashes, CAS-first chunk JSON, and optional inspect APIs. No embedding,
dense/lexical index, or publication activation occurs. Token counting uses a deterministic
stdlib-only approximate tokenizer (no new dependency); sizes are development defaults under an
explicit configuration hash, not production-promoted policy.

**Five implemented families (criterion 14 minimum):**

| Family | Role |
| --- | --- |
| `fixed_token` | Simple fixed-window baseline |
| `recursive` | Required normal-path baseline (§13.5) |
| `page_based` | One retrieval unit per canonical page |
| `parent_child` | Structure-aware hierarchical projection (production-policy core) |
| `table_aware` | Table row/header representations (production-policy core) |

The strategy registry enumerates the full §13.2 family list. Unimplemented families remain
`not_implemented` and must fail closed if requested. Parent-child and table-aware are **implemented
and benchmarked in development**; criterion 15 “production-ready” stays unclaimed until sealed
holdout + promotion gates exist.

**Phase boundary:** Phase 2C does not embed, index, publish to retrieval, run OCR/VLM, reopen
Docling, or claim production promotion. Phase 2D owns dense/lexical indexes and atomic publication.

---

## Contract and safety invariants

1. Canonical document versions and raw artifacts are never mutated by chunking.
2. A `ChunkSet` is a new append-only fact bound to exact `document_version_id`, canonical content
   hash, strategy identity, and configuration hash.
3. Every chunk names ordered source element IDs; lineage must resolve inside the source canonical
   document.
4. Chunk IDs are deterministic from chunk-set identity, ordinal, source-element IDs, and text hash.
5. Rerunning identical inputs/configuration yields identical chunk-set bytes and hash.
6. Documents remain non-searchable: no production index table or publish API consumes chunks.
7. `DocumentProcessingLifecycle` may gain `chunked`; it must not gain `published`/`searchable`.
8. Failures are typed and sanitized; chunk text never enters HTTP error bodies.
9. No new third-party dependency without explicit dependency-governance approval.
10. Acceptance-matrix rows close only with direct proof; partial evidence stays partial.

---

## File structure

- `packages/contracts/src/rsi_atlas_contracts/chunking.py` — Chunk / ChunkSet / strategy contracts
- `packages/contracts/tests/test_chunking.py` — strict contract tests
- `packages/contracts/tests/fixtures/chunk_set_v1.json` — golden ChunkSet fixture
- `packages/ingestion/src/rsi_atlas_ingestion/chunking/` — pure family implementations + registry
- `packages/ingestion/src/rsi_atlas_ingestion/chunk_service.py` — CAS + manifest orchestration
- `packages/ingestion/benchmarks/chunking/` — frozen intrinsic benchmark corpus
- `packages/ingestion/tests/test_chunkers.py` — family unit tests
- `packages/ingestion/tests/test_chunk_benchmark.py` — corpus integrity + intrinsic metrics
- `packages/ingestion/tests/test_chunk_persistence.py` — CAS/DB idempotency
- `migrations/0007_chunk_sets.sql` — append-only chunk set versions + events
- `services/engine/...` — optional chunk inspect endpoints (Task 5)
- Swift inspect models/views only if Task 5 lands native surface

---

### Task 1: Strict chunking contracts

**Files:**

- Create: `packages/contracts/src/rsi_atlas_contracts/chunking.py`
- Modify: `packages/contracts/src/rsi_atlas_contracts/__init__.py`
- Modify: `packages/contracts/src/rsi_atlas_contracts/document_parsing.py` (lifecycle `chunked` only)
- Create: `packages/contracts/tests/test_chunking.py`
- Create: `packages/contracts/tests/fixtures/chunk_set_v1.json`

**Interfaces:**

- `ChunkStrategyFamily` — full §13.2 enum
- `ChunkStrategyIdentity` — family, strategy_id, version, configuration_hash
- `Chunk`, `ChunkRelationship`, `ChunkSetQuality`, `ChunkSet`, `ChunkSetManifest`
- Helpers: `chunk_identifier`, `chunk_set_identifier`, `build_chunk_set`

- [x] **Step 1: Write RED contract tests**

Unknown fields forbidden; schema `1.0.0`; UTC timestamps; deterministic IDs; source element
non-empty ordered uniqueness; text/hash binding; family/config binding; no searchable lifecycle;
unimplemented-family rejection at manifest builder when requested.

- [x] **Step 2: Run RED**

```bash
uv run pytest packages/contracts/tests/test_chunking.py -q
```

- [x] **Step 3: Implement smallest strict models**

- [x] **Step 4: Verify and commit**

```bash
uv run pytest packages/contracts/tests/test_chunking.py packages/contracts/tests/test_document_parsing.py -q
uv run ruff check packages/contracts
uv run ruff format --check packages/contracts
uv run mypy packages/contracts/src
git add packages/contracts
git commit -m "feat: define chunk set contracts"
```

---

### Task 2: Five pure chunker implementations

**Files:**

- Create: `packages/ingestion/src/rsi_atlas_ingestion/chunking/__init__.py`
- Create: `packages/ingestion/src/rsi_atlas_ingestion/chunking/tokenize.py`
- Create: `packages/ingestion/src/rsi_atlas_ingestion/chunking/fixed_token.py`
- Create: `packages/ingestion/src/rsi_atlas_ingestion/chunking/recursive.py`
- Create: `packages/ingestion/src/rsi_atlas_ingestion/chunking/page_based.py`
- Create: `packages/ingestion/src/rsi_atlas_ingestion/chunking/parent_child.py`
- Create: `packages/ingestion/src/rsi_atlas_ingestion/chunking/table_aware.py`
- Create: `packages/ingestion/src/rsi_atlas_ingestion/chunking/registry.py`
- Create: `packages/ingestion/tests/test_chunkers.py`

**Behavior:**

- Input: `CanonicalDocument` (+ optional table element metadata already on elements).
- Output: `ChunkSet` for the requested implemented family.
- `fixed_token`: pack normalized element text into windows of ~400 tokens, structural overlap 0.
- `recursive`: split by heading → paragraph → sentence-ish separators with max ~400 tokens.
- `page_based`: one chunk per page concatenating page elements in reading order.
- `parent_child`: heading/section parents (~900–1800 tokens) with child passages (~250–450);
  emit parent/child relationships.
- `table_aware`: for each `kind=table` element emit a full-table chunk plus row-level chunks with
  repeated header context when row structure is available in normalized text; non-table text falls
  back to page-based packing for that family set.
- Registry: only the five families above are callable; others raise `ChunkStrategyNotImplemented`.

- [x] **Step 1: RED tests for each family**

Determinism, lineage, token bounds (soft development thresholds), empty-page rejection, crypto
token/numeric preservation, parent-child edges, table split behavior.

- [x] **Step 2: Implement**

- [x] **Step 3: Verify and commit**

```bash
uv run pytest packages/ingestion/tests/test_chunkers.py -q
uv run ruff check packages/ingestion
uv run ruff format --check packages/ingestion
uv run mypy packages/ingestion/src
git add packages/ingestion
git commit -m "feat: implement five chunking families"
```

---

### Task 3: Frozen chunk benchmark corpus

**Files:**

- Create: `packages/ingestion/benchmarks/chunking/manifest.json`
- Create: `packages/ingestion/benchmarks/chunking/golden/*.json`
- Create: `packages/ingestion/benchmarks/chunking/README.md`
- Create: `packages/ingestion/tests/test_chunk_benchmark.py`
- Optional: `script/build_chunk_benchmark_fixtures.py` if synthetic canonical inputs are generated

**Corpus:** Reuse Phase 2B development canonical fixtures / synthetic multi-element documents covering
headings, paragraphs, tables, and crypto identifiers. Freeze expected chunk counts, content hashes,
intrinsic quality floors (token distribution, broken-sentence rate, table-split rate, section-path
completeness where applicable) per family.

- [x] **Step 1: RED corpus integrity tests**
- [x] **Step 2: Freeze goldens**
- [x] **Step 3: Verify and commit**

```bash
uv run pytest packages/ingestion/tests/test_chunk_benchmark.py -q
git add packages/ingestion/benchmarks/chunking packages/ingestion/tests/test_chunk_benchmark.py
git commit -m "test: freeze chunker intrinsic benchmarks"
```

---

### Task 4: CAS-first ChunkSet persistence

**Files:**

- Create: `migrations/0007_chunk_sets.sql`
- Create: `packages/ingestion/src/rsi_atlas_ingestion/chunk_service.py`
- Modify: `packages/storage/...` repository methods as needed
- Create: `packages/ingestion/tests/test_chunk_persistence.py`

**Behavior:** Write chunk-set JSON to CAS before committing append-only DB rows. Idempotent on
`(tenant, workspace, document_version_id, strategy_id, configuration_hash)`. Lifecycle event
`ChunkSetRecorded`. No index writes.

- [x] **Step 1: RED persistence/idempotency/corruption tests**
- [x] **Step 2: Migration + service**
- [x] **Step 3: Verify and commit**

```bash
RSI_ATLAS_TEST_DATABASE_URL="$(./infra/local/postgres.sh test-url)" \
  uv run pytest packages/ingestion/tests/test_chunk_persistence.py -q
git add migrations packages/ingestion packages/storage
git commit -m "feat: persist versioned chunk sets"
```

---

### Task 5: Processing API chunk inspection (development)

**Files:**

- Modify: processing pipeline / engine API
- Optional Swift Evidence chunk inspector if cheap after API contracts

Expose list/get for chunk sets bound to a canonical document version. Keep non-searchable wording
in responses. Skip native UI if time-bound; API + Python contract tests are the minimum.

- [x] **Step 1: RED API tests**
- [x] **Step 2: Implement**
- [x] **Step 3: Commit**

```bash
git commit -m "feat: inspect development chunk sets"
```

---

### Task 6: Gates, ledgers, Phase 2C closure

Update README, `docs/production-plan.md`, roadmap status, and acceptance-matrix **only** with
directly proven partial evidence for criteria 14/22 portions. Keep criterion 15 and Appendix D
“Chunking” as not fully proven until parent-child/table production promotion + labelled retrieval
benchmark exist. Do not claim Phase 2D.

- [x] **Step 1: Run gates and update ledgers**

Proven at closure: `uv lock --check`, ruff check/format, mypy, full pytest **973** passed,
Swift **44** passed. Tip code evidence through `d6e49b0`; Docling remains blocked; no
embeddings/indexes/publication; criterion 15 unclaimed.

```bash
uv lock --check
uv run ruff check packages services infra
uv run ruff format --check packages services infra
uv run mypy packages services infra
RSI_ATLAS_TEST_DATABASE_URL="$(./infra/local/postgres.sh test-url)" uv run pytest -q
swift test --package-path apps/macos
git diff --check
git commit -m "docs: close five-chunker development slice"
```

- [x] **Step 2: Commit Phase 2C closure**

---

## Development qualification thresholds (intrinsic only)

| Metric | Development floor |
| --- | --- |
| Deterministic rerun hash | 100% identical |
| Source element lineage resolve | 100% |
| Oversized chunk rate (>1800 tokens parent / >450 child) | recorded; soft warn only |
| Crypto/numeric token preservation | 100% on frozen fixtures |
| Unimplemented family request | fail closed |

Retrieval metrics (Recall@k, etc.) are Phase 2D / evaluation-plane work.

---

## Explicit non-goals

- Embeddings, pgvector writes, lexical indexes, Tantivy
- Atomic retrieval publication / searchable lifecycle
- Docling, OCR, scanned PDF, production parser promotion
- Semantic-breakpoint / late-chunking / agentic families (registry only)
- New tokenizer or NLP dependencies
