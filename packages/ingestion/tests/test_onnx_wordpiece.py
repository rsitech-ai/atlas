"""WordPiece + ONNX embedder tests (no silent network)."""

from __future__ import annotations

import os
from importlib.util import find_spec
from pathlib import Path

import pytest
from rsi_atlas_contracts import EmbeddingPromotionClass
from rsi_atlas_ingestion.embedding.bert_wordpiece import BertWordPieceTokenizer
from rsi_atlas_ingestion.embedding.offline_onnx import (
    OfflineArtifactUnavailable,
    OfflineOnnxEmbedder,
)

_HAS_ORT = find_spec("onnxruntime") is not None


def _tiny_vocab(path: Path) -> None:
    # Minimal BERT-shaped vocab for algorithm checks (not MiniLM weights).
    path.write_text(
        "\n".join(
            [
                "[PAD]",
                "[UNK]",
                "[CLS]",
                "[SEP]",
                "hello",
                "world",
                ",",
                "!",
                "un",
                "##known",
            ]
        )
        + "\n",
        encoding="utf-8",
    )


def test_wordpiece_encodes_known_tokens(tmp_path: Path) -> None:
    vocab = tmp_path / "vocab.txt"
    _tiny_vocab(vocab)
    tokenizer = BertWordPieceTokenizer(vocab, max_seq_length=16)
    input_ids, attention_mask, token_type_ids = tokenizer.encode("Hello, world!")
    assert input_ids[0] == 2  # [CLS]
    assert input_ids[-1] == 3  # [SEP]
    assert input_ids[1:-1] == [4, 6, 5, 7]  # hello , world !
    assert attention_mask == [1] * len(input_ids)
    assert token_type_ids == [0] * len(input_ids)


def test_wordpiece_falls_back_to_unk_for_oov(tmp_path: Path) -> None:
    vocab = tmp_path / "vocab.txt"
    _tiny_vocab(vocab)
    tokenizer = BertWordPieceTokenizer(vocab, max_seq_length=16)
    input_ids, _, _ = tokenizer.encode("zzz")
    assert input_ids == [2, 1, 3]  # CLS UNK SEP


def test_wordpiece_subword_split(tmp_path: Path) -> None:
    vocab = tmp_path / "vocab.txt"
    _tiny_vocab(vocab)
    tokenizer = BertWordPieceTokenizer(vocab, max_seq_length=16)
    input_ids, _, _ = tokenizer.encode("unknown")
    assert input_ids == [2, 8, 9, 3]  # CLS un ##known SEP


def test_real_minilm_artifact_optional() -> None:
    """Skip unless owner-local artifact dir is provided (no network in tests)."""
    if not _HAS_ORT:
        pytest.skip("onnxruntime optional extra not installed")
    root = Path.home() / ".cache" / "rsi-atlas" / "models" / "oss_minilm_l6_v2"
    env_root = Path(os.environ.get("RSI_ATLAS_EMBEDDING_ARTIFACT_DIR", ""))
    artifact = env_root if str(env_root) and env_root.is_dir() else root
    if not (artifact / "manifest.json").is_file() or not (artifact / "vocab.txt").is_file():
        pytest.skip(f"MiniLM artifact+vocab not present at {artifact}")
    embedder = OfflineOnnxEmbedder(artifact)
    assert embedder.model.promotion_class is EmbeddingPromotionClass.CANDIDATE
    assert embedder.model.dimensions == 384
    vector = embedder.embed_text("hello world")
    assert len(vector) == 384
    assert abs(sum(v * v for v in vector) ** 0.5 - 1.0) < 1e-5


def test_offline_onnx_fail_closed_missing_dir(tmp_path: Path) -> None:
    with pytest.raises(OfflineArtifactUnavailable):
        OfflineOnnxEmbedder(tmp_path / "missing")
