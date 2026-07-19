"""Fail-closed offline ONNX embedder (optional onnxruntime + owner artifact)."""

from __future__ import annotations

import json
import math
from hashlib import sha256
from pathlib import Path
from typing import Any

from rsi_atlas_contracts import EmbeddingModelIdentity, EmbeddingPromotionClass, validate_vector

from rsi_atlas_ingestion.embedding.bert_wordpiece import BertWordPieceTokenizer
from rsi_atlas_ingestion.embedding.deterministic import EmbeddingError

try:
    import onnxruntime as _ort  # type: ignore
except ImportError:  # pragma: no cover - optional dependency
    _ort = None

_ALLOWED_LICENSES = frozenset({"Apache-2.0", "MIT", "BSD-2-Clause", "BSD-3-Clause"})
_TRANSFORMER_INPUTS = frozenset({"input_ids", "attention_mask", "token_type_ids"})


class OfflineArtifactUnavailable(EmbeddingError):
    """Raised when the pinned ONNX artifact or runtime is missing."""


class OfflineOnnxEmbedder:
    """Load a hash-pinned local ONNX embedding model. No network I/O.

    Supports:
    - MiniLM-style transformer ONNX (input_ids / attention_mask [/ token_type_ids])
      with owner-supplied vocab.txt + mean pooling + L2 normalize
    - legacy single string-tensor ONNX exports

    ponytail: ceiling=owner install + onnxruntime + pinned vocab; upgrade=ModelRegistry lease
    """

    def __init__(self, artifact_dir: Path) -> None:
        self._artifact_dir = artifact_dir
        manifest_path = artifact_dir / "manifest.json"
        if not manifest_path.is_file():
            raise OfflineArtifactUnavailable(
                f"embedding artifact manifest missing: {manifest_path}"
            )
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        license_id = str(manifest.get("license", ""))
        if license_id not in _ALLOWED_LICENSES:
            raise OfflineArtifactUnavailable(f"disallowed embedding license: {license_id}")
        onnx_path = artifact_dir / str(manifest["onnx_file"])
        expected = str(manifest["onnx_sha256"])
        if not onnx_path.is_file():
            raise OfflineArtifactUnavailable(f"onnx weights missing: {onnx_path}")
        actual = sha256(onnx_path.read_bytes()).hexdigest()
        if actual != expected:
            raise OfflineArtifactUnavailable(
                f"onnx sha256 mismatch: expected={expected} actual={actual}"
            )
        if _ort is None:
            raise OfflineArtifactUnavailable(
                "onnxruntime not installed; install rsi-atlas-ingestion[onnx] "
                "or use TokenHashEmbedder"
            )
        session: Any = _ort.InferenceSession(
            onnx_path.as_posix(), providers=["CPUExecutionProvider"]
        )
        self._session = session
        input_names = {item.name for item in session.get_inputs()}
        self._input_names = input_names
        self._mode = _infer_mode(input_names)
        self._tokenizer: BertWordPieceTokenizer | None = None
        if self._mode == "transformer":
            self._tokenizer = _load_tokenizer(artifact_dir, manifest)
        dims = int(manifest["dimensions"])
        config_hash = sha256(
            json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        self._model = EmbeddingModelIdentity(
            model_id=str(manifest["model_id"]),
            version=str(manifest["version"]),
            dimensions=dims,
            normalization="l2",
            configuration_hash=config_hash,
            promotion_class=EmbeddingPromotionClass.CANDIDATE,
        )
        self._policy_hash = config_hash
        self._dimensions = dims
        self._string_input_name = next(iter(input_names)) if self._mode == "string" else None

    @property
    def model(self) -> EmbeddingModelIdentity:
        return self._model

    @property
    def input_policy_hash(self) -> str:
        return self._policy_hash

    def embed_text(self, text: str) -> tuple[float, ...]:
        if not text or not text.strip():
            raise EmbeddingError("empty embedding text")
        if self._mode == "transformer":
            assert self._tokenizer is not None
            input_ids, attention_mask, token_type_ids = self._tokenizer.encode(text)
            feeds: dict[str, Any] = {
                "input_ids": [input_ids],
                "attention_mask": [attention_mask],
            }
            if "token_type_ids" in self._input_names:
                feeds["token_type_ids"] = [token_type_ids]
            outputs = self._session.run(None, feeds)
            vector = _mean_pool_l2(
                last_hidden_state=outputs[0],
                attention_mask=attention_mask,
                dimensions=self._dimensions,
            )
        else:
            assert self._string_input_name is not None
            # ponytail: ceiling=string-tensor exports only; MiniLM uses transformer path
            outputs = self._session.run(None, {self._string_input_name: [[text]]})
            flat = outputs[0].reshape(-1)
            vector = tuple(float(x) for x in flat[: self._dimensions])
            if len(vector) != self._dimensions:
                raise EmbeddingError("onnx output dimension mismatch")
            vector = _l2_normalize(vector)
        validate_vector(vector, dimensions=self._dimensions)
        return vector


def _infer_mode(input_names: set[str]) -> str:
    if "input_ids" in input_names and "attention_mask" in input_names:
        return "transformer"
    if len(input_names) == 1 and not (input_names & _TRANSFORMER_INPUTS):
        return "string"
    raise OfflineArtifactUnavailable(
        f"unsupported onnx inputs {sorted(input_names)}; "
        "need input_ids+attention_mask or a single string tensor"
    )


def _load_tokenizer(artifact_dir: Path, manifest: dict[str, Any]) -> BertWordPieceTokenizer:
    tokenizer_kind = str(manifest.get("tokenizer", "none"))
    if tokenizer_kind in {"none", ""}:
        raise OfflineArtifactUnavailable(
            "transformer onnx requires tokenizer+vocab in manifest "
            "(re-run script/install_embedding_model.py --download)"
        )
    if tokenizer_kind not in {"bert_wordpiece_v1", "bert_wordpiece"}:
        raise OfflineArtifactUnavailable(f"unsupported tokenizer: {tokenizer_kind}")
    vocab_file = str(manifest.get("vocab_file", "vocab.txt"))
    vocab_path = artifact_dir / vocab_file
    if not vocab_path.is_file():
        raise OfflineArtifactUnavailable(f"vocab missing: {vocab_path}")
    expected_vocab = manifest.get("vocab_sha256")
    if expected_vocab is not None:
        actual_vocab = sha256(vocab_path.read_bytes()).hexdigest()
        if actual_vocab != str(expected_vocab):
            raise OfflineArtifactUnavailable(
                f"vocab sha256 mismatch: expected={expected_vocab} actual={actual_vocab}"
            )
    max_seq = int(manifest.get("max_seq_length", 256))
    return BertWordPieceTokenizer(vocab_path, max_seq_length=max_seq)


def _mean_pool_l2(
    *,
    last_hidden_state: Any,
    attention_mask: list[int],
    dimensions: int,
) -> tuple[float, ...]:
    """Sentence-transformers mean_tokens pooling then L2 normalize (stdlib)."""
    # last_hidden_state: [1, seq, dim] ndarray or nested sequence
    sequence = last_hidden_state[0]
    seq_len = len(attention_mask)
    if len(sequence) < seq_len:
        raise EmbeddingError("onnx sequence shorter than attention mask")
    dim = min(dimensions, len(sequence[0]))
    sums = [0.0] * dim
    weight = 0.0
    for index, flag in enumerate(attention_mask):
        if flag == 0:
            continue
        weight += 1.0
        token = sequence[index]
        for axis in range(dim):
            sums[axis] += float(token[axis])
    if weight == 0.0:
        raise EmbeddingError("zero attention weight")
    pooled = tuple(value / weight for value in sums)
    if len(pooled) != dimensions:
        raise EmbeddingError("onnx output dimension mismatch")
    return _l2_normalize(pooled)


def _l2_normalize(vector: tuple[float, ...]) -> tuple[float, ...]:
    norm = math.sqrt(sum(value * value for value in vector))
    if norm == 0.0:
        raise EmbeddingError("zero embedding norm")
    return tuple(value / norm for value in vector)


__all__ = [
    "OfflineArtifactUnavailable",
    "OfflineOnnxEmbedder",
]
