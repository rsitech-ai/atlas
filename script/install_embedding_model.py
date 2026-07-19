"""Install a hash-pinned local embedding ONNX artifact (no silent network)."""

from __future__ import annotations

import argparse
import json
import shutil
import sys
import urllib.error
import urllib.request
from hashlib import sha256
from pathlib import Path

# Pinned in docs/dependency-governance/embedding-model-approval.md — do not change lightly.
PINNED_MINILM_COMMIT = "1110a243fdf4706b3f48f1d95db1a4f5529b4d41"
PINNED_MINILM_ONNX_URL = (
    "https://huggingface.co/sentence-transformers/all-MiniLM-L6-v2/"
    f"resolve/{PINNED_MINILM_COMMIT}/onnx/model.onnx"
)
PINNED_MINILM_VOCAB_URL = (
    "https://huggingface.co/sentence-transformers/all-MiniLM-L6-v2/"
    f"resolve/{PINNED_MINILM_COMMIT}/vocab.txt"
)
PINNED_MINILM_ONNX_SHA256 = "6fd5d72fe4589f189f8ebc006442dbb529bb7ce38f8082112682524616046452"
PINNED_MINILM_VOCAB_SHA256 = "07eced375cec144d27c900241f3e339478dec958f92fddbc551f295c992038a3"
PINNED_MINILM_MODEL_ID = "oss_minilm_l6_v2"
PINNED_MINILM_VERSION = "st-1110a243"
PINNED_MINILM_DIMENSIONS = 384
PINNED_MINILM_LICENSE = "Apache-2.0"
PINNED_MINILM_BYTES = 90_405_214
PINNED_MINILM_MAX_SEQ = 256
PINNED_MINILM_VOCAB_FILE = "vocab.txt"


def _sha256_file(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def _write_manifest(
    *,
    artifact_dir: Path,
    model_id: str,
    version: str,
    dimensions: int,
    license_id: str,
    onnx_file: str,
    onnx_sha256: str,
    source_url: str | None = None,
    vocab_file: str | None = None,
    vocab_sha256: str | None = None,
    max_seq_length: int | None = None,
) -> Path:
    if vocab_file is not None and vocab_sha256 is not None:
        tokenizer_fields: dict[str, object] = {
            "tokenizer": "bert_wordpiece_v1",
            "vocab_file": vocab_file,
            "vocab_sha256": vocab_sha256,
            "max_seq_length": max_seq_length or PINNED_MINILM_MAX_SEQ,
            "pooling": "mean_tokens",
            "notes": (
                "Pinned MiniLM ONNX + vocab; OfflineOnnxEmbedder runs WordPiece → "
                "ONNX → mean pool → L2. Still EmbeddingPromotionClass.CANDIDATE — "
                "not sealed-holdout PRODUCTION."
            ),
        }
    else:
        tokenizer_fields = {
            "tokenizer": "none",
            "notes": (
                "No vocab installed; usable only for string-input ONNX exports. "
                "For MiniLM transformer weights, re-run with --download or "
                "--vocab-source. Prefer RSI_ATLAS_EMBEDDER=oss_token_hash when "
                "tokenizer files are absent."
            ),
        }
    manifest: dict[str, object] = {
        "model_id": model_id,
        "version": version,
        "dimensions": dimensions,
        "license": license_id,
        "onnx_file": onnx_file,
        "onnx_sha256": onnx_sha256,
        **tokenizer_fields,
    }
    if source_url is not None:
        manifest["source_url"] = source_url
    path = artifact_dir / "manifest.json"
    path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def _download_url(url: str, staging: Path) -> int:
    try:
        with (
            urllib.request.urlopen(url, timeout=120) as response,
            staging.open("wb") as handle,
        ):
            while True:
                chunk = response.read(1024 * 1024)
                if not chunk:
                    break
                handle.write(chunk)
    except urllib.error.URLError as error:
        print(f"download failed: {error}", file=sys.stderr)
        if staging.exists():
            staging.unlink()
        return 4
    return 0


def _install_from_source(
    *,
    artifact_dir: Path,
    source: Path,
    expected_sha256: str,
    model_id: str,
    version: str,
    dimensions: int,
    license_id: str,
    onnx_file: str,
    source_url: str | None = None,
    vocab_source: Path | None = None,
    expected_vocab_sha256: str | None = None,
    vocab_file: str = PINNED_MINILM_VOCAB_FILE,
    max_seq_length: int = PINNED_MINILM_MAX_SEQ,
) -> int:
    if not source.is_file():
        print(f"source missing: {source}", file=sys.stderr)
        return 2
    digest = _sha256_file(source)
    if digest != expected_sha256.lower():
        print(f"sha256 mismatch: expected={expected_sha256} actual={digest}", file=sys.stderr)
        return 3
    vocab_digest: str | None = None
    if vocab_source is not None:
        if expected_vocab_sha256 is None:
            print("--expected-vocab-sha256 required with --vocab-source", file=sys.stderr)
            return 2
        if not vocab_source.is_file():
            print(f"vocab source missing: {vocab_source}", file=sys.stderr)
            return 2
        vocab_digest = _sha256_file(vocab_source)
        if vocab_digest != expected_vocab_sha256.lower():
            print(
                f"vocab sha256 mismatch: expected={expected_vocab_sha256} actual={vocab_digest}",
                file=sys.stderr,
            )
            return 3
    artifact_dir.mkdir(parents=True, exist_ok=True)
    target = artifact_dir / onnx_file
    shutil.copy2(source, target)
    if vocab_source is not None and vocab_digest is not None:
        shutil.copy2(vocab_source, artifact_dir / vocab_file)
    _write_manifest(
        artifact_dir=artifact_dir,
        model_id=model_id,
        version=version,
        dimensions=dimensions,
        license_id=license_id,
        onnx_file=onnx_file,
        onnx_sha256=digest,
        source_url=source_url,
        vocab_file=vocab_file if vocab_digest is not None else None,
        vocab_sha256=vocab_digest,
        max_seq_length=max_seq_length if vocab_digest is not None else None,
    )
    print(f"installed {target} sha256={digest}")
    if vocab_digest is not None:
        print(f"installed {artifact_dir / vocab_file} sha256={vocab_digest}")
    print("export RSI_ATLAS_EMBEDDER=onnx")
    print(f"export RSI_ATLAS_EMBEDDING_ARTIFACT_DIR={artifact_dir}")
    if vocab_digest is None:
        print(
            "note: no vocab installed; transformer MiniLM needs --vocab-source or --download. "
            "oss_token_hash remains the no-artifact dense default."
        )
    else:
        print(
            "note: ONNX+vocab ready for OfflineOnnxEmbedder (candidate, not sealed PRODUCTION)."
        )
    return 0


def _download_pinned(*, artifact_dir: Path, onnx_file: str) -> int:
    artifact_dir.mkdir(parents=True, exist_ok=True)
    staging = artifact_dir / f".{onnx_file}.partial"
    print(f"downloading pinned MiniLM ONNX ({PINNED_MINILM_BYTES} bytes)…", file=sys.stderr)
    print(f"url={PINNED_MINILM_ONNX_URL}", file=sys.stderr)
    code = _download_url(PINNED_MINILM_ONNX_URL, staging)
    if code != 0:
        return code
    digest = _sha256_file(staging)
    if digest != PINNED_MINILM_ONNX_SHA256:
        print(
            f"sha256 mismatch after download: expected={PINNED_MINILM_ONNX_SHA256} actual={digest}",
            file=sys.stderr,
        )
        staging.unlink(missing_ok=True)
        return 3
    target = artifact_dir / onnx_file
    staging.replace(target)

    vocab_staging = artifact_dir / f".{PINNED_MINILM_VOCAB_FILE}.partial"
    print("downloading pinned MiniLM vocab.txt…", file=sys.stderr)
    print(f"url={PINNED_MINILM_VOCAB_URL}", file=sys.stderr)
    code = _download_url(PINNED_MINILM_VOCAB_URL, vocab_staging)
    if code != 0:
        return code
    vocab_digest = _sha256_file(vocab_staging)
    if vocab_digest != PINNED_MINILM_VOCAB_SHA256:
        print(
            f"vocab sha256 mismatch: expected={PINNED_MINILM_VOCAB_SHA256} actual={vocab_digest}",
            file=sys.stderr,
        )
        vocab_staging.unlink(missing_ok=True)
        return 3
    vocab_target = artifact_dir / PINNED_MINILM_VOCAB_FILE
    vocab_staging.replace(vocab_target)

    _write_manifest(
        artifact_dir=artifact_dir,
        model_id=PINNED_MINILM_MODEL_ID,
        version=PINNED_MINILM_VERSION,
        dimensions=PINNED_MINILM_DIMENSIONS,
        license_id=PINNED_MINILM_LICENSE,
        onnx_file=onnx_file,
        onnx_sha256=digest,
        source_url=PINNED_MINILM_ONNX_URL,
        vocab_file=PINNED_MINILM_VOCAB_FILE,
        vocab_sha256=vocab_digest,
        max_seq_length=PINNED_MINILM_MAX_SEQ,
    )
    print(f"installed {target} sha256={digest}")
    print(f"installed {vocab_target} sha256={vocab_digest}")
    print("export RSI_ATLAS_EMBEDDER=onnx")
    print(f"export RSI_ATLAS_EMBEDDING_ARTIFACT_DIR={artifact_dir}")
    print(
        "note: install rsi-atlas-ingestion[onnx], then OfflineOnnxEmbedder is usable "
        "(candidate; not sealed-holdout PRODUCTION)."
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Install an owner-supplied ONNX embedding artifact with hash pin. "
            "Network download only with explicit --download."
        )
    )
    parser.add_argument("--artifact-dir", type=Path, required=True)
    parser.add_argument(
        "--source",
        type=Path,
        help="Local already-downloaded ONNX (required unless --download)",
    )
    parser.add_argument(
        "--expected-sha256",
        help="Required with --source; defaults to pinned MiniLM hash with --download",
    )
    parser.add_argument(
        "--download",
        action="store_true",
        help="Opt-in fetch of the governance-pinned MiniLM ONNX + vocab (egress intentional)",
    )
    parser.add_argument(
        "--vocab-source",
        type=Path,
        help="Local vocab.txt for transformer MiniLM (optional with --source)",
    )
    parser.add_argument(
        "--expected-vocab-sha256",
        help="Required with --vocab-source",
    )
    parser.add_argument("--model-id", default=PINNED_MINILM_MODEL_ID)
    parser.add_argument("--version", default=PINNED_MINILM_VERSION)
    parser.add_argument("--dimensions", type=int, default=PINNED_MINILM_DIMENSIONS)
    parser.add_argument("--license", default=PINNED_MINILM_LICENSE)
    parser.add_argument("--onnx-file", default="model.onnx")
    parser.add_argument("--max-seq-length", type=int, default=PINNED_MINILM_MAX_SEQ)
    args = parser.parse_args(argv)

    if args.download and args.source is not None:
        print("use either --download or --source, not both", file=sys.stderr)
        return 2
    if args.download:
        return _download_pinned(artifact_dir=args.artifact_dir, onnx_file=args.onnx_file)
    if args.source is None or args.expected_sha256 is None:
        print("--source and --expected-sha256 are required unless --download", file=sys.stderr)
        return 2
    return _install_from_source(
        artifact_dir=args.artifact_dir,
        source=args.source,
        expected_sha256=args.expected_sha256,
        model_id=args.model_id,
        version=args.version,
        dimensions=args.dimensions,
        license_id=args.license,
        onnx_file=args.onnx_file,
        vocab_source=args.vocab_source,
        expected_vocab_sha256=args.expected_vocab_sha256,
        max_seq_length=args.max_seq_length,
    )


if __name__ == "__main__":
    raise SystemExit(main())
