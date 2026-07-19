# RSI Atlas PDF benchmark corpus

This directory is the frozen, offline Phase 2B parser corpus. It is test evidence, not a production
promotion set. Every PDF and golden file is pinned by `manifest.json`; the dependency-free generator
must reproduce the committed bytes exactly.

## Partitions and authority

- `development` contains synthetic construction and edge fixtures used while writing adapters.
- `calibration` contains representative synthetic layouts used to freeze thresholds.
- `validation` is visible to implementation writers and may support development qualification only.
- `adversarial` contains active-content, malformed, encrypted, resource-boundary, and disagreement
  cases that must fail closed or route to review.

All generated fixtures are released under CC0-1.0. Their provenance is
`deterministic-local-generator:rsi-atlas-pdf-corpus-1`. The corpus is intentionally synthetic so it
does not import third-party text, personal data, or network dependencies. Production promotion
remains blocked until an independently controlled sealed holdout is evaluated after code,
configuration, and thresholds are frozen.

## Reproduction

```bash
uv run python script/build_pdf_benchmark_fixtures.py --check
```

Use `--write` only when intentionally changing the corpus. A corpus change requires review of the
generator, PDF bytes, golden evidence, hashes, thresholds, and downstream benchmark baselines.

After `--write`, use a Python runtime containing `pdfplumber`, `pdfminer.six`, and `pypdf` to run:

```bash
python script/build_pdf_benchmark_fixtures.py --observe
```

This writes independent page-count, text, glyph-box, encryption, malformed-file, and decoded-stream
evidence to the ignored `.superpowers/sdd/phase-2b-pdf-corpus-inspection.json` path. The evidence is
never a qualification input and is intentionally not committed. A corpus review must transform
every independently observed glyph box into PDF source user space and compare it with its golden
containment envelope. For the rotated fixture the evidence retains both the extractor-space and
inverse-transformed source-space boxes and verifies its MediaBox, CropBox, and 90-degree rotation.

The encrypted fixture uses the deterministic user password `atlas` and owner password `owner`.
Those values are public test data, not secrets. The URI fixture intentionally declares its single
inert `.invalid` locator in the manifest; every undeclared locator is a test failure. No fixture
should be opened in a browser or allowed to initiate network access.

## Golden semantics

Goldens freeze expected page count, raw ASCII strings, typed exact tokens, source-space bounding
regions, and the preflight route. Token categories preserve compound EVM, Solana, and Bitcoin
identifiers, dates, percentages, currencies, symbols, and finding IDs literally. Coordinates use PDF
bottom-left points encoded as six-decimal strings. Each declared region is a containment envelope:
an independently observed glyph box, expanded by the frozen one-point comparison tolerance, must
fit inside it. Image-only and encrypted fixtures truthfully have no expected raw text. Parser
adapters may add warnings or unsupported evidence, but they may not fabricate missing text,
coordinates, pages, or passing results.

The benchmark manifest names exact small, medium, and long fixture membership; page/byte boundaries;
cold- and warm-process lifecycle/cache semantics; reference hardware, OS, and runtime; run counts;
per-class p95 and peak-RSS ceilings; zero-failure/zero-timeout rules; and the required result-record
schema. Filesystem cache state is recorded rather than pretending that macOS provides a reliable
per-run cold-disk reset.

## Visual inspection

Render every page with the bundled offline Poppler tools before accepting a corpus change. Inspect
text clipping, reading-order intent, font changes, tables, figure/caption placement, crop and
rotation behavior, and image-only truth. Store screenshots only under ignored review-evidence paths;
do not commit renderer caches or screenshots to this corpus.

The 2,001-page limit fixture is intentionally repetitive and uses a shared content stream to keep
the repository small. The decompression fixture invokes a referenced Form XObject whose compressed
and decoded sizes, ratio, accounting scope, byte limit, and reject outcome are frozen in the
manifest. The malformed fixture corrupts both its catalog root reference and `startxref`, and a
strict independent parser must reject it. A grammar-aware, non-executing structural walker decodes
comments, arbitrary whitespace, escaped names, literal/UTF-16 hexadecimal strings, indirect objects,
and bounded Flate object streams. It inventories every action subtype and optional-Type file spec,
resolves and inspects JavaScript and embedded-file streams, and fails closed on ambiguous or
unsupported designated resources. Generic URI schemes and UNC locators must match the exact manifest
allowlist. The sole external resource is the inert `https://example.invalid/governance` URI. The
parser-disagreement fixture uses overlapping blocks and must remain a review outcome rather than a
silently accepted ordering.
