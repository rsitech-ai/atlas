# Phase 2D Dense/Lexical Indexes + Atomic Publication Implementation Plan

> **Execution:** Follow repository TDD and review gates task by task. Do not begin Phase 3
> retrieval/research workflows until every Phase 2D acceptance item below is either proven or
> explicitly left as development-only.

**Goal:** Turn a Phase 2C `ChunkSet` into versioned staging dense (pgvector) and lexical
(PostgreSQL FTS) indexes, then atomically activate a retrieval publication so a document becomes
searchable only after count/lineage verification—without production embedding-model promotion,
Tantivy, OCR, Docling, or hybrid query fusion.

**User-visible outcome:** From development processing surfaces, an analyst can index a persisted
chunk set, inspect staging dense/lexical row counts and identifier hits, and publish/activate (or
rollback) a retrieval version. Unpublished and superseded versions remain invisible to search.

**Architecture:** Keep Phase 2A–2C admissions, canonical versions, and chunk sets immutable.
Phase 2D adds (1) embedding records bound to chunk text hashes, (2) staging dense + lexical +
exact-identifier index tables, (3) an append-only publication manifest, and (4) a single-row
active pointer flipped inside one transaction. Development embeddings use a deterministic
stdlib-only hash→vector adapter (not a production-promoted model). Optional Tantivy stays out.

**Tech Stack:** Python 3.11+, Pydantic strict contracts, Psycopg 3, PostgreSQL 17 + pgvector,
raw SQL migration `0008`, existing CAS artifact store, pytest + real test DB.

## Global Constraints

1. Canonical documents and chunk sets are never mutated by indexing or publication.
2. A retrieval publication is a new append-only fact bound to exact chunk-set id/hash, embedding
   policy hash, and index configuration hash.
3. Content is searchable only while an **active** publication pointer names a verified version.
4. Staging rows never participate in search queries.
5. Atomic activation: verify counts/lineage → commit manifest → activate → supersede prior → emit
   `DocumentPublished` in one DB transaction (or fail with no partial active flip).
6. Embedding model selection is **not** production-promoted; development uses deterministic local
   vectors marked `ponytail:` with upgrade path to governed ModelArtifact embeddings.
7. No Docling, OCR, Tantivy, remote embeddings, or Phase 3 fusion/rerank.
8. Acceptance-matrix rows close only with direct proof; criteria 16/18 get development partial
   evidence only. Criterion 15 stays unclaimed.
9. No new third-party dependency without governance approval.
10. Failures are typed and sanitized; chunk text never enters HTTP error bodies.

---

## File structure

- `packages/contracts/src/rsi_atlas_contracts/publication.py` — embedding / publication contracts
- `packages/contracts/tests/test_publication.py` — strict contract tests
- `packages/ingestion/src/rsi_atlas_ingestion/embedding/` — development embedding adapter
- `packages/ingestion/src/rsi_atlas_ingestion/index_service.py` — build staging indexes
- `packages/ingestion/src/rsi_atlas_ingestion/publication_service.py` — atomic activate/rollback
- `packages/ingestion/tests/test_embeddings.py` — vector validation + determinism
- `packages/ingestion/tests/test_index_publication.py` — staging + atomic activate/rollback
- `migrations/0008_retrieval_indexes.sql` — staging/active tables + publication manifests
- `packages/storage/.../document_processing_repository.py` — commit/activate helpers
- `services/engine/...` — optional index/publish inspect APIs (Task 5)
- README / production-plan / roadmap / acceptance-matrix — honest partial evidence only

---

### Task 1: Strict indexing + publication contracts

**Files:**

- Create: `packages/contracts/src/rsi_atlas_contracts/publication.py`
- Modify: `packages/contracts/src/rsi_atlas_contracts/document_parsing.py` — add
  `INDEXED`, `PUBLISHED` to `DocumentProcessingLifecycle` (not `searchable`)
- Modify: `packages/contracts/src/rsi_atlas_contracts/__init__.py`
- Modify: `packages/contracts/tests/test_chunking.py` — allow `indexed`/`published`; forbid bare `searchable`
- Create: `packages/contracts/tests/test_publication.py`

**Interfaces:**

- `EmbeddingModelIdentity` — model_id, version, dimensions, normalization, configuration_hash,
  `promotion_class` (fixture cannot be production)
- `PublicationManifest` — chunk_set binding, dense/lexical CAS artifacts, cardinality checks,
  lifecycle `indexed` | `published` with searchable coupling
- Helper: `build_publication_manifest_id`

- [x] **Step 1: Write RED contract tests**
- [x] **Step 2: Run RED**
- [x] **Step 3: Implement smallest strict models**
- [ ] **Step 4: Verify and commit**

```bash
uv run pytest packages/contracts/tests/test_publication.py packages/contracts/tests/test_chunking.py -q
uv run ruff check packages/contracts && uv run ruff format --check packages/contracts
uv run mypy packages/contracts/src
git commit -m "feat: define retrieval index publication contracts"
```

---

### Task 2: Development embedding adapter

**Files:**

- Create: `packages/ingestion/src/rsi_atlas_ingestion/embedding/__init__.py`
- Create: `packages/ingestion/src/rsi_atlas_ingestion/embedding/deterministic.py`
- Create: `packages/ingestion/tests/test_embeddings.py`

**Behavior:**

- `ponytail: ceiling=hash-pseudo-embedding (not semantic); upgrade=governed ModelArtifact EMBEDDINGS`
- Fixed development dimensions (64), L2-normalize, finite non-zero vectors
- Identical text hash → identical vector; content-hash cache keyed by (policy, text_hash)
- Reject empty text / zero-norm / wrong dimension

- [ ] **Step 1: RED tests**
- [ ] **Step 2: Implement**
- [ ] **Step 3: Commit**

```bash
git commit -m "feat: add deterministic development embeddings"
```

---

### Task 3: Migration + staging index builders

**Files:**

- Create: `migrations/0008_retrieval_indexes.sql`
- Create: `packages/ingestion/src/rsi_atlas_ingestion/index_service.py`
- Extend: `packages/storage/.../document_processing_repository.py`
- Create/extend tests in `packages/ingestion/tests/test_index_publication.py`

**Schema (sketch):**

- `atlas_ingestion.embedding_sets` — append-only CAS-bound embedding set manifests
- `atlas_ingestion.retrieval_index_versions` — version_id, chunk_set_id, status
  (`staging`|`active`|`superseded`|`failed`), dense/lexical/exact counts, content hashes
- `atlas_ingestion.dense_chunk_embeddings` — version_id, chunk_id, embedding `vector(64)`, text_hash
- `atlas_ingestion.lexical_chunk_documents` — version_id, chunk_id, body, `tsv` tsvector, GIN
- `atlas_ingestion.exact_identifier_hits` — version_id, chunk_id, identifier_kind, identifier_value
- `atlas_ingestion.retrieval_publication_manifests` — append-only publication JSON + artifact
- `atlas_ingestion.document_retrieval_active` — one active version per
  (tenant, workspace, document_version_id, strategy_id) updated only inside publication txn
- Append-only triggers on evidence tables; active pointer is intentionally mutable

**IndexService:**

1. Load chunk set from CAS/manifest
2. Embed all chunks (cache by text hash)
3. Write staging dense + lexical + exact rows under a new `staging` version
4. Verify cardinality == chunk count; every chunk_id/text_hash matches
5. Persist embedding-set + index-version manifests at lifecycle `index_validated`
6. Do **not** flip active pointer

- [ ] **Step 1: RED persistence/staging tests**
- [ ] **Step 2: Migration + repository + IndexService**
- [ ] **Step 3: Commit**

```bash
git commit -m "feat: stage dense and lexical retrieval indexes"
```

---

### Task 4: Atomic publication activate + rollback

**Files:**

- Create: `packages/ingestion/src/rsi_atlas_ingestion/publication_service.py`
- Extend repository + tests

**PublicationService:**

```text
load staging version
→ verify counts and lineage
→ commit publication manifest (CAS-first)
→ BEGIN
     supersede prior active (if any)
     set status=active on new version
     upsert document_retrieval_active pointer
     emit DocumentPublished event
   COMMIT
```

Rollback / kill mid-flight leaves prior active unchanged. Failed activation marks version `failed`
without becoming searchable. Re-running identical inputs is idempotent on content hashes.

Search helper used only in tests: `search_lexical(active_only=True)` must miss staging rows.

- [ ] **Step 1: RED atomicity tests (incl. simulated mid-txn failure)**
- [ ] **Step 2: Implement**
- [ ] **Step 3: Commit**

```bash
git commit -m "feat: atomically publish retrieval index versions"
```

---

### Task 5: Development inspect/publish APIs (optional but preferred)

**Files:**

- `services/engine/src/rsi_atlas_engine/api.py` / `ingestion.py`
- `services/engine/tests/test_document_processing_api.py`

Endpoints (loopback development):

- `indexing:start` — build staging indexes for a chunk set
- list/get index versions (include status, counts, searchable flag derived from active pointer)
- `publication:activate` / `publication:rollback`

Keep wording honest: development-only; not production-promoted embedding policy.

- [ ] **Step 1: RED API tests**
- [ ] **Step 2: Implement**
- [ ] **Step 3: Commit**

```bash
git commit -m "feat: inspect and activate development retrieval indexes"
```

---

### Task 6: Gates, ledgers, Phase 2D closure

Update README, `docs/production-plan.md`, roadmap, and acceptance-matrix **only** with directly
proven partial evidence for criteria **16** (local dense/lexical indexing) and **18** (atomic
rollbackable publication). Do not claim:

- production embedding model promotion
- Tantivy / BM25 adapter
- criterion 15 parent-child/table production-ready
- Phase 3 hybrid retrieval / EvidencePacket
- interrupt/resume (criterion 20) unless separately proven
- complete offline ingestion closure for all of 10–24

```bash
uv lock --check
uv run ruff check packages services infra
uv run ruff format --check packages services infra
uv run mypy packages services infra
RSI_ATLAS_TEST_DATABASE_URL="$(./infra/local/postgres.sh test-url)" uv run pytest -q
swift test --package-path apps/macos
git diff --check
git commit -m "docs: close dense/lexical index publication slice"
```

---

## Development qualification thresholds

| Metric | Development floor |
| --- | --- |
| Embedding determinism (same text hash) | 100% identical vectors |
| Vector checks (dim/finite/non-zero) | 100% reject on violation |
| Staging cardinality vs chunk count | exact match required to validate |
| Active search visibility of staging | 0 hits |
| Atomic activate under injected failure | prior active retained |
| Identical re-index content hash | idempotent |

---

## Explicit non-goals

- Production embedding model selection / ModelArtifact promotion
- Tantivy or external BM25
- Hybrid fusion, reranking, EvidencePacket (Phase 3 / §16)
- Docling, OCR, scanned PDF, parser production promotion
- Intelligence extractors (§15)
- Human interrupt/resume workflow UI (criterion 20) unless already present
- Claiming full closure of acceptance criteria 10–24
