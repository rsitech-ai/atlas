# Chunking intrinsic benchmark corpus

Frozen development fixtures for the five Phase 2C chunking families.

- Partition: `development` only (not a sealed holdout; not production promotion).
- Input: synthetic two-page canonical crypto document with headings, paragraphs, a table, and
  address/percentage tokens.
- Tokenizer: deterministic approximate whitespace split under `CHUNK_CONFIGURATION_HASH`.
- Metrics: determinism, lineage resolve, crypto-token preservation, frozen chunk-set hashes.

Retrieval metrics (Recall@k, etc.) are out of scope until Phase 2D / evaluation plane.

Regenerate goldens only when intentionally changing development chunk configuration:

```bash
# recreate via the generator snippet used in the Phase 2C commit, or re-run the
# packages/ingestion/tests/test_chunk_benchmark.py freeze helper if added later
```
