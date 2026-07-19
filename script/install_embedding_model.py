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
PINNED_MINILM_ONNX_URL = (
    "https://huggingface.co/sentence-transformers/all-MiniLM-L6-v2/"
    "resolve/bc57282b0c1c7b9f64118cbf472744b7988c1177/onnx/model.onnx"
)
PINNED_MINILM_ONNX_SHA256 = "6fd5d72fe4589f189f8ebc006442dbb529bb7ce38f8082112682524616046452"
PINNED_MINILM_MODEL_ID = "oss_minilm_l6_v2"
PINNED_MINILM_VERSION = "st-bc57282"
PINNED_MINILM_DIMENSIONS = 384
PINNED_MINILM_LICENSE = "Apache-2.0"
PINNED_MINILM_BYTES = 90_405_214


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
) -> Path:
    manifest: dict[str, object] = {
        "model_id": model_id,
        "version": version,
        "dimensions": dimensions,
        "license": license_id,
        "onnx_file": onnx_file,
        "onnx_sha256": onnx_sha256,
        "tokenizer": "none",
        "notes": (
            "Transformer MiniLM ONNX expects input_ids/attention_mask; "
            "OfflineOnnxEmbedder currently accepts string-input ONNX only. "
            "Use RSI_ATLAS_EMBEDDER=oss_token_hash until tokenizer wiring lands."
        ),
    }
    if source_url is not None:
        manifest["source_url"] = source_url
    path = artifact_dir / "manifest.json"
    path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


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
) -> int:
    if not source.is_file():
        print(f"source missing: {source}", file=sys.stderr)
        return 2
    digest = _sha256_file(source)
    if digest != expected_sha256.lower():
        print(f"sha256 mismatch: expected={expected_sha256} actual={digest}", file=sys.stderr)
        return 3
    artifact_dir.mkdir(parents=True, exist_ok=True)
    target = artifact_dir / onnx_file
    shutil.copy2(source, target)
    _write_manifest(
        artifact_dir=artifact_dir,
        model_id=model_id,
        version=version,
        dimensions=dimensions,
        license_id=license_id,
        onnx_file=onnx_file,
        onnx_sha256=digest,
        source_url=source_url,
    )
    print(f"installed {target} sha256={digest}")
    print("export RSI_ATLAS_EMBEDDER=onnx")
    print(f"export RSI_ATLAS_EMBEDDING_ARTIFACT_DIR={artifact_dir}")
    print(
        "note: production-local dense default remains oss_token_hash until MiniLM "
        "tokenizer/pooling is wired; ONNX path stays fail-closed without a compatible artifact."
    )
    return 0


def _download_pinned(*, artifact_dir: Path, onnx_file: str) -> int:
    artifact_dir.mkdir(parents=True, exist_ok=True)
    staging = artifact_dir / f".{onnx_file}.partial"
    print(f"downloading pinned MiniLM ONNX ({PINNED_MINILM_BYTES} bytes)…", file=sys.stderr)
    print(f"url={PINNED_MINILM_ONNX_URL}", file=sys.stderr)
    try:
        with (
            urllib.request.urlopen(PINNED_MINILM_ONNX_URL, timeout=120) as response,
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
    _write_manifest(
        artifact_dir=artifact_dir,
        model_id=PINNED_MINILM_MODEL_ID,
        version=PINNED_MINILM_VERSION,
        dimensions=PINNED_MINILM_DIMENSIONS,
        license_id=PINNED_MINILM_LICENSE,
        onnx_file=onnx_file,
        onnx_sha256=digest,
        source_url=PINNED_MINILM_ONNX_URL,
    )
    print(f"installed {target} sha256={digest}")
    print("export RSI_ATLAS_EMBEDDER=onnx")
    print(f"export RSI_ATLAS_EMBEDDING_ARTIFACT_DIR={artifact_dir}")
    print(
        "note: weights are pinned; OfflineOnnxEmbedder still requires a string-input ONNX "
        "or tokenizer upgrade. Prefer RSI_ATLAS_EMBEDDER=oss_token_hash for runtime."
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
        help="Opt-in fetch of the governance-pinned MiniLM ONNX (egress intentional)",
    )
    parser.add_argument("--model-id", default=PINNED_MINILM_MODEL_ID)
    parser.add_argument("--version", default=PINNED_MINILM_VERSION)
    parser.add_argument("--dimensions", type=int, default=PINNED_MINILM_DIMENSIONS)
    parser.add_argument("--license", default=PINNED_MINILM_LICENSE)
    parser.add_argument("--onnx-file", default="model.onnx")
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
    )


if __name__ == "__main__":
    raise SystemExit(main())
