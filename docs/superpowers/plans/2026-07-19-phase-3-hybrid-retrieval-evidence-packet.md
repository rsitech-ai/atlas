# Phase 3 Hybrid Retrieval + EvidencePacket (Development) Implementation Plan

> **Execution:** Follow repository TDD and review gates task by task. Do not claim production
> retrieval, LangGraph research workflows, or sealed holdout metrics until each item is proven.

**Goal:** Answer a frozen development research question against **active** Phase 2D publications
only by running dense (fixture vectors) + lexical (PostgreSQL FTS) + exact-identifier candidate
generation, fusing into a typed `EvidencePacket`, without production embedding promotion, Tantivy,
Docling, OCR, or multi-agent research.

**User-visible outcome:** From a loopback development API, an analyst can submit a query scoped to
a workspace/document set, inspect a typed retrieval plan and fused evidence packet with citations
bound to chunk/page lineage, and see staging/unpublished indexes excluded.

**Architecture:** Consume Phase 2D active pointers only. No mutation of chunk sets or index rows.
Development embedder remains `fixture_hash_v1`. Fusion is deterministic RRF (or equivalent
stdlib-only rank fusion) with explicit plane traces. Rerank/model judges stay out of this slice.

**Tech Stack:** Existing contracts + Psycopg/pgvector + pytest test DB. No new third-party
dependency without governance approval.

## Global Constraints

1. Search hits only `document_retrieval_active` publications.
2. Fixture embeddings only; production embedding models remain blocked.
3. Docling, OCR, Tantivy, remote models, LangGraph specialists: out of scope.
4. Acceptance-matrix criteria 25–40 get development partial evidence only when proven; do not
   close broader research criteria (41–60).
5. Failures are typed and sanitized; chunk text never enters HTTP error bodies.

## Non-goals

- Production embedding / reranker promotion
- Multi-hop repair loops, contradiction judges, coverage abstention beyond simple empty packets
- Full §17–18 research/report plane
- Native Swift retrieval UI (optional later)

## Tasks (outline)

### Task 1: Retrieval contracts
`ResearchQuery`, `QueryIntent` (minimal), `RetrievalPlan`/`RetrievalStep`, `EvidencePacket`,
plane candidate records, fusion manifest. Strict Pydantic; tests first.

### Task 2: Active-only retrievers
Dense (pgvector cosine on fixture dim), lexical (FTS), exact identifier. Unit + DB tests proving
staging invisibility (reuse 2D helpers).

### Task 3: Deterministic fusion → EvidencePacket
RRF (or documented equivalent) with plane provenance; empty/degraded packets when no active
indexes.

### Task 4: Loopback retrieve API
`POST .../retrieval:search` (name TBD) returning plan + packet summaries.

### Task 5: Gates and honest ledgers
Update README / production-plan / roadmap / acceptance-matrix with partial evidence only.

## First verification command (after Task 1 RED)

```bash
uv run pytest packages/contracts/tests/test_retrieval.py -q
```
