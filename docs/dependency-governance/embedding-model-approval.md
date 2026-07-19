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

MiniLM-class weights may be installed only via explicit owner action (no silent egress):

```bash
# Preferred offline path: owner already downloaded the file
uv run python script/install_embedding_model.py \
  --artifact-dir "$RSI_ATLAS_DATA_ROOT/models/oss_minilm_l6_v2" \
  --source /path/to/already-downloaded/model.onnx \
  --expected-sha256 6fd5d72fe4589f189f8ebc006442dbb529bb7ce38f8082112682524616046452

# Explicit opt-in download of the governance-pinned MiniLM ONNX (egress intentional)
uv run python script/install_embedding_model.py \
  --artifact-dir "$RSI_ATLAS_DATA_ROOT/models/oss_minilm_l6_v2" \
  --download
```

### Pinned MiniLM ONNX (Apache-2.0)

| Field | Value |
| --- | --- |
| Source | `sentence-transformers/all-MiniLM-L6-v2` (Hugging Face) |
| Commit | `bc57282b0c1c7b9f64118cbf472744b7988c1177` |
| URL | `https://huggingface.co/sentence-transformers/all-MiniLM-L6-v2/resolve/bc57282b0c1c7b9f64118cbf472744b7988c1177/onnx/model.onnx` |
| SHA256 | `6fd5d72fe4589f189f8ebc006442dbb529bb7ce38f8082112682524616046452` |
| Size | 90405214 bytes |
| Dimensions | 384 |
| License | Apache-2.0 |

Manifest fields required: `model_id`, `version`, `dimensions`, `onnx_sha256`,
`tokenizer_sha256` (or `tokenizer: none` for hash-tokenized / string-input models), `license`
(must be Apache-2.0 / MIT / BSD-*). Runtime loads only after hash verify.

### Runtime honesty

- Default tests: `fixture_hash_v1`
- Practical production-local dense without tokenizer wiring: `oss_token_hash_v1`
- `OfflineOnnxEmbedder` currently accepts **string-input** ONNX only (ponytail ceiling).
  Official MiniLM ONNX expects `input_ids` / `attention_mask`; installing the pinned weights
  verifies supply-chain hash pinning but does **not** silently upgrade embed quality until
  tokenizer+pooling lands. Fail-closed remains if artifact/runtime missing when
  `RSI_ATLAS_EMBEDDER=onnx`.

### Not allowed

- Remote embedding endpoints / OpenAI / proprietary APIs
- Silent Hugging Face / CDN downloads from application code (engine/retrieval/ingest path)
- Claiming `EmbeddingPromotionClass.PRODUCTION` without sealed holdout evaluation (§35)
- Docling-bundled embedders

### Rollback

- Remove `TokenHashEmbedder` / `OfflineOnnxEmbedder` usage from DI; keep fixture default
- Delete optional `onnxruntime` extra and regenerate `uv.lock` if added
- Delete owner model artifacts under the data root

## Authority

- Allows dependency lock change for optional `onnxruntime` only when an install path is wired
- Allows model artifacts only via explicit owner install + hash pin (or explicit `--download`)
- Does **not** allow runtime network, production criterion closure, push, or Apple signing
