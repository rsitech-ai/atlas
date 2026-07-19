# Embedding model dependency approval

Status: **blocked** (fixture-only)

Phase 2D may use only the in-repo deterministic `fixture_hash_v1` hash→vector adapter for
development dense staging and atomic publication wiring. No third-party embedding model,
tokenizer, ONNX/MLX runtime, or remote embedding API is approved.

## Decision

Blocked on 2026-07-19 under Phase 2D development. Production embedding selection remains a
governed evaluation (§35) requiring frozen benchmark, licensing/supply-chain review, resource
evidence, versioned production policy, and rollback.

Allowed:

- `rsi_atlas_ingestion.embedding.FixtureEmbedder` (stdlib SHA-256 → L2 unit vector)
- `EmbeddingPromotionClass.DEVELOPMENT_FIXTURE` with `fixture_` model_id prefix only

Not allowed:

- Any new PyPI embedding/tokenizer dependency
- Remote embedding endpoints
- Claiming `EmbeddingPromotionClass.PRODUCTION` for fixture models
- Tantivy or other external BM25 adapters

Rollback for fixture embedder is deletion of the adapter and index rows that reference
`fixture_hash_v1`. No lockfile change is authorized by this record.
