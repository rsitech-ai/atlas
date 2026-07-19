# Reranker dependency approval

Status: **approved** (lexical OSS production-local; neural cross-encoder optional/fail-closed)

## Decision

Approved on 2026-07-19 by actor `andrzej:oss-production-ready-instruction` under the user's
OSS production-ready instruction.

### Allowed

- `lexical_overlap_rerank_v1` (stdlib): post-RRF token-overlap / BM25-lite reordering of fused
  evidence items. No new dependency. Default production-local path when neural rerank is absent.
- Optional future `OfflineOnnxCrossEncoder` only with the same owner-controlled artifact + hash
  pin pattern as embeddings; fail-closed if missing. Not required for this slice.

### Not allowed

- Proprietary / cloud rerank APIs
- Silent model downloads
- Claiming calibrated LLM-judge rerank without evaluation promotion

### Rollback

Delete `rsi_atlas_retrieval.rerank` usage from `HybridRetrievalService`; fusion stays RRF-only.
