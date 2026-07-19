"""Install a hash-pinned local embedding ONNX artifact (no network)."""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from hashlib import sha256
from pathlib import Path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Install an owner-supplied ONNX embedding artifact with hash pin"
    )
    parser.add_argument("--artifact-dir", type=Path, required=True)
    parser.add_argument("--source", type=Path, required=True, help="Local already-downloaded ONNX")
    parser.add_argument("--expected-sha256", required=True)
    parser.add_argument("--model-id", default="oss_minilm_onnx_v1")
    parser.add_argument("--version", default="cand-1")
    parser.add_argument("--dimensions", type=int, default=384)
    parser.add_argument("--license", default="Apache-2.0")
    parser.add_argument("--onnx-file", default="model.onnx")
    args = parser.parse_args(argv)

    if not args.source.is_file():
        print(f"source missing: {args.source}", file=sys.stderr)
        return 2
    digest = sha256(args.source.read_bytes()).hexdigest()
    if digest != args.expected_sha256.lower():
        print(f"sha256 mismatch: expected={args.expected_sha256} actual={digest}", file=sys.stderr)
        return 3
    args.artifact_dir.mkdir(parents=True, exist_ok=True)
    target = args.artifact_dir / args.onnx_file
    shutil.copy2(args.source, target)
    manifest = {
        "model_id": args.model_id,
        "version": args.version,
        "dimensions": args.dimensions,
        "license": args.license,
        "onnx_file": args.onnx_file,
        "onnx_sha256": digest,
        "tokenizer": "none",
    }
    (args.artifact_dir / "manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(f"installed {target} sha256={digest}")
    print(f"export RSI_ATLAS_EMBEDDER=onnx")
    print(f"export RSI_ATLAS_EMBEDDING_ARTIFACT_DIR={args.artifact_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
