# Phase 3 Hybrid Retrieval / Specialists / Cited Reports Implementation Plan

> **Execution:** Follow repository TDD and review gates task by task. Do not claim Section 33
> criteria 4–8 or 25–60 closed. Do not begin Phase 4 collectors until every Phase 3 acceptance
> item below is either proven or explicitly left as development-only.

**Goal:** From a frozen material question against **active** Phase 2D publications, produce an
inspectable retrieval plan, hybrid `EvidencePacket` (dense + lexical + exact), one bounded
Document Evidence specialist finding, assertion-first synthesis, exact citation bindings, and a
versioned report draft with immutable review—without production embeddings, Docling, OCR,
Tantivy, LangGraph durability, calibrated judges, or multi-chain planes.

**User-visible outcome:** Development loopback APIs accept a `ResearchQuery`, return an
inspectable fused evidence packet (or honest abstention), run the Document Evidence specialist,
and emit a cited report draft that fails closed when citations/coverage are insufficient.

**Architecture:** Keep Phase 2A–2D admissions, canonical versions, chunk sets, and publications
immutable. Phase 3 adds (1) strict retrieval/research/report contracts, (2) active-only hybrid
candidate generation + intent-weighted RRF, (3) deterministic coverage/abstention + replay
record, (4) Document Evidence specialist with schema-validated I/O, (5) assertion → citation →
report draft pipeline with immutable review events. Production cross-encoder/LLM rerankers and
the remaining specialist roster stay blocked behind governance.

**Tech Stack:** Python 3.11+, Pydantic strict contracts, Psycopg 3, PostgreSQL 17 + pgvector,
raw SQL migration `0009`, existing CAS artifact store, pytest + real test DB. No new third-party
dependency. No LangGraph in this development slice (`ponytail:` upgrade = durable graph later).

## Global Constraints

1. Search only **active** retrieval publications; staging rows never participate.
2. Every run freezes a `DataCutoffManifest` hash; “current” means locally published evidence.
3. Fusion ranks remain inspectable; relevance and reliability stay separate scores.
4. Specialists receive only task + permitted evidence; no SQL/HTTP/shell/filesystem/secrets.
5. Assertions precede prose; writers cannot silently introduce material unsupported claims.
6. Citations bind before rendering; generated summaries cannot be primary citations.
7. Review decisions are append-only immutable events.
8. Embedding/reranker/model promotion stays blocked; fixture embeddings + deterministic fusion only.
9. No Docling, OCR, Tantivy, remote models, or Phase 4 chain/market collectors.
10. Acceptance-matrix rows get **development partial** evidence only; no false criterion closure.
11. Failures are typed and sanitized; chunk/report text never enters HTTP error bodies.

## Development-slice acceptance (must prove)

1. Strict contracts reject invalid query/plan/candidate/packet/finding/assertion/citation/report.
2. Dense + lexical + exact candidates generate only from active publications.
3. Intent-weighted RRF fusion is deterministic and inspectable (component ranks preserved).
4. Coverage matrix + insufficient evidence yield honest abstention (no fabricated packet).
5. Exact replay reconstructs a stored EvidencePacket from recorded hashes/versions.
6. Document Evidence specialist I/O is schema-validated; unsupported completion is explicit.
7. Assertions bind evidence before report prose; citation locator + excerpt hash validate.
8. Report draft publication gate fails closed on missing citations/coverage.
9. Immutable review event records approve / reject / request_more_evidence.
10. Loopback APIs expose retrieve → specialist → report draft without claiming native UI.

## Explicitly out of scope (blocked / later)

- Production embedding model, cross-encoder, LLM reranker, calibrated judges
- Remaining specialist roster (tokenomics, security, …) and LangGraph interrupt/resume
- Time-series / chain-snapshot / market / GitHub / governance planes (Phase 4)
- Native Research Canvas / Report Studio / Evidence Inspector citation UI (criteria 4–8)
- Criteria 25–60 closed; multi-ecosystem due diligence; monitoring-driven research

---

## File structure

- `packages/contracts/src/rsi_atlas_contracts/retrieval.py` — query/plan/candidate/packet
- `packages/contracts/src/rsi_atlas_contracts/research.py` — specialist/assertion/citation/report
- `packages/contracts/tests/test_retrieval.py`, `test_research.py`
- `packages/retrieval/` — hybrid search, fusion, coverage, replay services
- `packages/research/` — document specialist, assertion builder, report gate
- `migrations/0009_retrieval_research_runs.sql` — run/packet/report/review tables
- `packages/storage/.../retrieval_research_repository.py` — persistence helpers
- `services/engine/...` — loopback retrieve / specialist / report APIs
- README / production-plan / roadmap / acceptance-matrix — honest partial evidence only

---

### Task 1: Strict retrieval + research contracts

**Files:**

- Create: `packages/contracts/src/rsi_atlas_contracts/retrieval.py`
- Create: `packages/contracts/src/rsi_atlas_contracts/research.py`
- Modify: `packages/contracts/src/rsi_atlas_contracts/__init__.py`
- Create: `packages/contracts/tests/test_retrieval.py`
- Create: `packages/contracts/tests/test_research.py`

**Interfaces (minimum):**

- `ResearchQuery`, `QueryFamily`, `DataCutoffManifest`, `RetrievalStep`, `RetrievalPlan`
- `EvidenceCandidate`, `EvidenceItemKind`, `CoverageStatus`, `CoverageCell`, `EvidencePacket`
- `SpecialistType` (document_evidence only in this slice), `SpecialistTask`, `SpecialistFinding`
- `ResearchAssertion`, `CitationRole`, `CitationBinding`, `ReportDraft`, `ReviewDecision`

- [ ] **Step 1: Write RED contract tests**
- [ ] **Step 2: Run RED**
- [ ] **Step 3: Implement smallest strict models**
- [ ] **Step 4: Verify and commit**

```bash
uv run pytest packages/contracts/tests/test_retrieval.py packages/contracts/tests/test_research.py -q
uv run ruff check packages/contracts && uv run ruff format --check packages/contracts
uv run mypy packages/contracts/src
git commit -m "feat: define hybrid retrieval and research contracts"
```

---

### Task 2: Active hybrid candidate generation

**Files:**

- Create: `packages/retrieval/` workspace package
- Create: `packages/retrieval/src/rsi_atlas_retrieval/search.py`
- Create: `packages/retrieval/tests/test_hybrid_search.py`
- Modify: storage repository — `search_dense_active`, `search_exact_active`

- [ ] **Step 1: RED** — staging invisible; active dense/lexical/exact return ranked candidates
- [ ] **Step 2: Implement search against `document_retrieval_active` only**
- [ ] **Step 3: Verify and commit**

```bash
RSI_ATLAS_TEST_DATABASE_URL="$(./infra/local/postgres.sh test-url)" \
  uv run pytest packages/retrieval/tests/test_hybrid_search.py -q
git commit -m "feat: search active dense lexical and exact indexes"
```

---

### Task 3: RRF fusion, coverage, EvidencePacket, replay

**Files:**

- Create: `packages/retrieval/src/rsi_atlas_retrieval/fusion.py`
- Create: `packages/retrieval/src/rsi_atlas_retrieval/coverage.py`
- Create: `packages/retrieval/src/rsi_atlas_retrieval/packet.py`
- Create: `packages/retrieval/tests/test_fusion_packet.py`

- [ ] **Step 1: RED** — deterministic RRF; inspectable component ranks; abstention; exact replay
- [ ] **Step 2: Implement fusion + coverage + packet assembly**
- [ ] **Step 3: Verify and commit**

```bash
uv run pytest packages/retrieval/tests/test_fusion_packet.py -q
git commit -m "feat: fuse hybrid candidates into inspectable evidence packets"
```

---

### Task 4: Document Evidence specialist + plan validation

**Files:**

- Create: `packages/research/` workspace package
- Create: `packages/research/src/rsi_atlas_research/planner.py`
- Create: `packages/research/src/rsi_atlas_research/document_specialist.py`
- Create: `packages/research/tests/test_document_specialist.py`

- [ ] **Step 1: RED** — invalid plans rejected; specialist returns schema-valid finding
- [ ] **Step 2: Deterministic extractive specialist (no LLM)**
- [ ] **Step 3: Verify and commit**

```bash
uv run pytest packages/research/tests/test_document_specialist.py -q
git commit -m "feat: validate plans and run document evidence specialist"
```

---

### Task 5: Assertions, citations, report draft, review

**Files:**

- Create: `packages/research/src/rsi_atlas_research/assertions.py`
- Create: `packages/research/src/rsi_atlas_research/citations.py`
- Create: `packages/research/src/rsi_atlas_research/reports.py`
- Create: `packages/research/tests/test_cited_reports.py`

- [ ] **Step 1: RED** — unsupported claim blocked; citation hash mismatch fails; review immutable
- [ ] **Step 2: Assertion → citation bind → report gate → review event**
- [ ] **Step 3: Verify and commit**

```bash
uv run pytest packages/research/tests/test_cited_reports.py -q
git commit -m "feat: bind citations and gate versioned report drafts"
```

---

### Task 6: Persistence + loopback APIs

**Files:**

- Create: `migrations/0009_retrieval_research_runs.sql`
- Create: `packages/storage/src/rsi_atlas_storage/retrieval_research_repository.py`
- Modify: `services/engine/src/rsi_atlas_engine/api.py` + tests

Endpoints (development loopback):

- `POST /v1/workspaces/{id}/research:retrieve` → EvidencePacket or abstention
- `POST /v1/workspaces/{id}/research/runs/{run_id}/specialist:document` → SpecialistFinding
- `POST /v1/workspaces/{id}/research/runs/{run_id}/reports:draft` → ReportDraft
- `POST /v1/workspaces/{id}/research/reports/{report_id}/review` → ReviewDecision

- [ ] **Step 1: RED API tests**
- [ ] **Step 2: Migration + repository + routes**
- [ ] **Step 3: Verify and commit**

```bash
RSI_ATLAS_TEST_DATABASE_URL="$(./infra/local/postgres.sh test-url)" \
  uv run pytest services/engine/tests/test_research_api.py packages/storage/tests -q
git commit -m "feat: expose research retrieve specialist and report APIs"
```

---

### Task 7: Honest docs + phase closure gate

**Files:**

- Modify: `docs/production-plan.md`, `docs/acceptance-matrix.md`,
  `docs/superpowers/plans/2026-07-18-full-product-delivery-roadmap.md`, README as needed
- Mark plan tasks complete; tip commit for evidence

Verification gate:

```bash
uv lock --check
uv run ruff check packages services infra
uv run ruff format --check packages services infra
uv run mypy packages services infra
RSI_ATLAS_TEST_DATABASE_URL="$(./infra/local/postgres.sh test-url)" uv run pytest -q
swift test --package-path apps/macos
```

- [ ] Full gate green
- [ ] Docs state development-only evidence; Docling/production embeddings still blocked
- [ ] Commit: `docs: close Phase 3 hybrid retrieval development slice`

---

## Rollback

Revert tip commits through Task 1; drop migration `0009` only on disposable DBs. Active Phase 2D
publications remain valid without Phase 3 tables.

## Next after this slice

- Production embedding + cross-encoder governance
- LangGraph durable research graph + interrupt/resume
- Remaining specialists; calibrated judges
- Native Research Canvas / Report Studio
- Phase 4 multi-chain planes feeding structured retrieval
