# Embedding model dependency approval

Status: **approved** (offline OSS production-local candidate + fixture retained)

Phase 2D fixture embeddings remain the default for tests. Production-local dense indexing
may use the governed offline OSS path below. No remote embedding API is approved. Silent
model download / egress is forbidden.

## Decision

Approved on 2026-07-19 by actor `andrzej:oss-production-ready-instruction` under the user's
instruction to make RSI Atlas as fully production-ready as possible with open-source
capabilities only (Apache/MIT/BSD; offline-first; no silent network).

Updated 2026-07-19: MiniLM ONNX path wired end-to-end (stdlib WordPiece + mean pool) when
owner artifact + vocab + optional `onnxruntime` are present. Still
`EmbeddingPromotionClass.CANDIDATE` — not sealed-holdout `PRODUCTION`.

### Allowed adapters

| Adapter | model_id | promotion_class | Dependency | Notes |
| --- | --- | --- | --- | --- |
| `DeterministicEmbedder` | `fixture_hash_v1` | `development_fixture` | stdlib | Tests / default DI |
| `TokenHashEmbedder` | `oss_token_hash_v1` | `candidate` | stdlib | Offline hashed n-gram projection; dim=64; no download |
| `OfflineOnnxEmbedder` | from artifact manifest | `candidate` | optional `onnxruntime` (MIT) + pinned vocab | Fail-closed if artifact, vocab, or runtime missing |

### Optional runtime dependency (SBOM-aware)

| Package | Version pin | License | Authority |
| --- | --- | --- | --- |
| `onnxruntime` | `>=1.20.0,<2` via `rsi-atlas-ingestion[onnx]` | MIT | Prior user production-OSS intent (`andrzej:oss-production-ready-instruction`); recorded in `uv.lock` for SBOM |

Transitive wheels (`numpy`, `protobuf`, `flatbuffers`) enter the lock only when the `onnx`
extra is resolved. No Hugging Face `tokenizers` / `transformers` — WordPiece is stdlib.

### Owner-controlled ONNX artifact install (optional)

MiniLM-class weights + vocab may be installed only via explicit owner action (no silent egress):

```bash
# Preferred offline path: owner already downloaded the files
uv run python script/install_embedding_model.py \
  --artifact-dir "$RSI_ATLAS_DATA_ROOT/models/oss_minilm_l6_v2" \
  --source /path/to/already-downloaded/model.onnx \
  --expected-sha256 6fd5d72fe4589f189f8ebc006442dbb529bb7ce38f8082112682524616046452 \
  --vocab-source /path/to/vocab.txt \
  --expected-vocab-sha256 07eced375cec144d27c900241f3e339478dec958f92fddbc551f295c992038a3

# Explicit opt-in download of the governance-pinned MiniLM ONNX + vocab (egress intentional)
uv run python script/install_embedding_model.py \
  --artifact-dir "$RSI_ATLAS_DATA_ROOT/models/oss_minilm_l6_v2" \
  --download
```

Enable runtime:

```bash
uv sync --package rsi-atlas-ingestion --extra onnx
export RSI_ATLAS_EMBEDDER=onnx
export RSI_ATLAS_EMBEDDING_ARTIFACT_DIR="$RSI_ATLAS_DATA_ROOT/models/oss_minilm_l6_v2"
```

### Pinned MiniLM ONNX + vocab (Apache-2.0)

| Field | Value |
| --- | --- |
| Source | `sentence-transformers/all-MiniLM-L6-v2` (Hugging Face) |
| Commit | `1110a243fdf4706b3f48f1d95db1a4f5529b4d41` |
| ONNX URL | `https://huggingface.co/sentence-transformers/all-MiniLM-L6-v2/resolve/1110a243fdf4706b3f48f1d95db1a4f5529b4d41/onnx/model.onnx` |
| ONNX SHA256 | `6fd5d72fe4589f189f8ebc006442dbb529bb7ce38f8082112682524616046452` |
| ONNX size | 90405214 bytes |
| Vocab URL | `https://huggingface.co/sentence-transformers/all-MiniLM-L6-v2/resolve/1110a243fdf4706b3f48f1d95db1a4f5529b4d41/vocab.txt` |
| Vocab SHA256 | `07eced375cec144d27c900241f3e339478dec958f92fddbc551f295c992038a3` |
| Dimensions | 384 |
| Max seq length | 256 |
| Pooling | mean_tokens + L2 |
| Tokenizer | stdlib `bert_wordpiece_v1` |
| License | Apache-2.0 |

Manifest fields required: `model_id`, `version`, `dimensions`, `onnx_sha256`,
`tokenizer` (`bert_wordpiece_v1` + `vocab_sha256` for MiniLM; or `tokenizer: none` for
string-input exports), `license` (must be Apache-2.0 / MIT / BSD-*). Runtime loads only
after hash verify.

### Runtime honesty

- Default tests: `fixture_hash_v1`
- Practical production-local dense without ONNX install: `oss_token_hash_v1`
- When artifact + vocab + `onnxruntime` are present, `OfflineOnnxEmbedder` runs the pinned
  MiniLM path (WordPiece → tensors → ONNX → mean pool → L2). Usable for development /
  production-local candidate dense. Still **not** sealed-holdout `PRODUCTION` (§35) without
  evaluation evidence.
- Fail-closed if artifact / vocab / runtime missing when `RSI_ATLAS_EMBEDDER=onnx`.

### Not allowed

- Remote embedding endpoints / OpenAI / proprietary APIs
- Silent Hugging Face / CDN downloads from application code (engine/retrieval/ingest path)
- Claiming `EmbeddingPromotionClass.PRODUCTION` without sealed holdout evaluation (§35)
- Docling-bundled embedders
- Adding `tokenizers` / `transformers` without a new governance record

### Rollback

- Remove `TokenHashEmbedder` / `OfflineOnnxEmbedder` usage from DI; keep fixture default
- Delete optional `onnxruntime` extra and regenerate `uv.lock`
- Delete owner model artifacts under the data root

## Authority

- Allows dependency lock change for optional `onnxruntime` (MIT) under this record
- Allows model artifacts only via explicit owner install + hash pin (or explicit `--download`)
- Does **not** allow runtime network, production criterion closure, push, or Apple signing
