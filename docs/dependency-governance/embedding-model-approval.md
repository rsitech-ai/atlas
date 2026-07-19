# Embedding model dependency approval

Status: **approved** (offline OSS production-local candidate + fixture retained)

Phase 2D fixture embeddings remain the default for tests. Production-local dense indexing
may use the governed offline OSS path below. No remote embedding API is approved. Silent
model download / egress is forbidden.

## Decision

Approved on 2026-07-19 by actor `andrzej:oss-production-ready-instruction` under the user's
instruction to make RSI Atlas as fully production-ready as possible with open-source
capabilities only (Apache/MIT/BSD; offline-first; no silent network).

### Allowed adapters

| Adapter | model_id | promotion_class | Dependency | Notes |
| --- | --- | --- | --- | --- |
| `DeterministicEmbedder` | `fixture_hash_v1` | `development_fixture` | stdlib | Tests / default DI |
| `TokenHashEmbedder` | `oss_token_hash_v1` | `candidate` | stdlib | Offline hashed n-gram projection; dim=64; no download |
| `OfflineOnnxEmbedder` | from artifact manifest | `candidate` | optional `onnxruntime` (MIT) | Fail-closed if artifact or runtime missing |

### Owner-controlled ONNX artifact install (optional)

MiniLM-class semantic quality requires an owner-installed local artifact (no silent egress):

```bash
# Example: place a pinned ONNX + tokenizer under the owner-private model root
uv run python script/install_embedding_model.py \
  --artifact-dir "$RSI_ATLAS_DATA_ROOT/models/oss_minilm_l6_v2" \
  --source /path/to/already-downloaded/model.onnx \
  --expected-sha256 <64-hex>
```

Manifest fields required: `model_id`, `version`, `dimensions`, `onnx_sha256`,
`tokenizer_sha256` (or `tokenizer: none` for hash-tokenized inputs), `license`
(must be Apache-2.0 / MIT / BSD-*). Runtime loads only after hash verify.

### Not allowed

- Remote embedding endpoints / OpenAI / proprietary APIs
- Silent Hugging Face / CDN downloads from application code
- Claiming `EmbeddingPromotionClass.PRODUCTION` without sealed holdout evaluation (§35)
- Docling-bundled embedders

### Rollback

- Remove `TokenHashEmbedder` / `OfflineOnnxEmbedder` usage from DI; keep fixture default
- Delete optional `onnxruntime` extra and regenerate `uv.lock` if added
- Delete owner model artifacts under the data root

## Authority

- Allows dependency lock change for optional `onnxruntime` only when an install path is wired
- Allows model artifacts only via explicit owner install + hash pin
- Does **not** allow runtime network, production criterion closure, push, or Apple signing
