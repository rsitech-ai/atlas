"""Tests for hash-pinned embedding artifact install (no live network)."""

from __future__ import annotations

import importlib.util
import json
from hashlib import sha256
from pathlib import Path

ROOT = Path(__file__).parents[1]
SCRIPT = ROOT / "script/install_embedding_model.py"


def _load_install():
    specification = importlib.util.spec_from_file_location("install_embedding_model", SCRIPT)
    assert specification is not None and specification.loader is not None
    module = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(module)
    return module


def test_install_from_source_writes_manifest(tmp_path: Path) -> None:
    install = _load_install()
    source = tmp_path / "model.onnx"
    payload = b"rsi-atlas-tiny-onnx-fixture-v1"
    source.write_bytes(payload)
    digest = sha256(payload).hexdigest()
    artifact_dir = tmp_path / "artifact"
    code = install.main(
        [
            "--artifact-dir",
            str(artifact_dir),
            "--source",
            str(source),
            "--expected-sha256",
            digest,
            "--model-id",
            "fixture_onnx_v1",
            "--version",
            "test-1",
            "--dimensions",
            "8",
            "--license",
            "Apache-2.0",
        ]
    )
    assert code == 0
    assert (artifact_dir / "model.onnx").read_bytes() == payload
    manifest = (artifact_dir / "manifest.json").read_text(encoding="utf-8")
    assert digest in manifest
    assert "fixture_onnx_v1" in manifest
    assert '"tokenizer": "none"' in manifest


def test_install_from_source_with_vocab(tmp_path: Path) -> None:
    install = _load_install()
    source = tmp_path / "model.onnx"
    source.write_bytes(b"onnx-bytes")
    digest = sha256(b"onnx-bytes").hexdigest()
    vocab = tmp_path / "vocab.txt"
    vocab.write_text("[PAD]\n[UNK]\n[CLS]\n[SEP]\n", encoding="utf-8")
    vocab_digest = sha256(vocab.read_bytes()).hexdigest()
    artifact_dir = tmp_path / "artifact"
    code = install.main(
        [
            "--artifact-dir",
            str(artifact_dir),
            "--source",
            str(source),
            "--expected-sha256",
            digest,
            "--vocab-source",
            str(vocab),
            "--expected-vocab-sha256",
            vocab_digest,
        ]
    )
    assert code == 0
    manifest = json.loads((artifact_dir / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["tokenizer"] == "bert_wordpiece_v1"
    assert manifest["vocab_sha256"] == vocab_digest
    assert (artifact_dir / "vocab.txt").read_bytes() == vocab.read_bytes()


def test_install_rejects_sha_mismatch(tmp_path: Path) -> None:
    install = _load_install()
    source = tmp_path / "model.onnx"
    source.write_bytes(b"payload")
    code = install.main(
        [
            "--artifact-dir",
            str(tmp_path / "out"),
            "--source",
            str(source),
            "--expected-sha256",
            "0" * 64,
        ]
    )
    assert code == 3


def test_pinned_download_constants_match_governance() -> None:
    install = _load_install()
    approval = (ROOT / "docs/dependency-governance/embedding-model-approval.md").read_text(
        encoding="utf-8"
    )
    assert install.PINNED_MINILM_ONNX_SHA256 in approval
    assert install.PINNED_MINILM_VOCAB_SHA256 in approval
    assert install.PINNED_MINILM_COMMIT in install.PINNED_MINILM_ONNX_URL
    assert install.PINNED_MINILM_COMMIT in approval
    assert "all-MiniLM-L6-v2" in install.PINNED_MINILM_ONNX_URL
    assert "--download" in approval


def test_main_missing_source_exits_2(tmp_path: Path) -> None:
    install = _load_install()
    assert install.main(["--artifact-dir", str(tmp_path / "a")]) == 2
