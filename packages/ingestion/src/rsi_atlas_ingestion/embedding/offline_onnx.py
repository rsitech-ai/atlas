"""Fail-closed offline ONNX embedder (optional onnxruntime + owner artifact)."""

from __future__ import annotations

import json
from hashlib import sha256
from pathlib import Path
from typing import Any

from rsi_atlas_contracts import EmbeddingModelIdentity, EmbeddingPromotionClass, validate_vector

from rsi_atlas_ingestion.embedding.deterministic import EmbeddingError

try:
    import onnxruntime as _ort  # type: ignore[import-not-found]
except ImportError:  # pragma: no cover - optional dependency
    _ort = None

_ALLOWED_LICENSES = frozenset({"Apache-2.0", "MIT", "BSD-2-Clause", "BSD-3-Clause"})


class OfflineArtifactUnavailable(EmbeddingError):
    """Raised when the pinned ONNX artifact or runtime is missing."""


class OfflineOnnxEmbedder:
    """Load a hash-pinned local ONNX embedding model. No network I/O.

    ponytail: ceiling=requires owner install + onnxruntime; upgrade=ModelRegistry lease
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
                "onnxruntime not installed; install optional extra or use TokenHashEmbedder"
            )
        session: Any = _ort.InferenceSession(
            onnx_path.as_posix(), providers=["CPUExecutionProvider"]
        )
        self._session = session
        self._input_name = session.get_inputs()[0].name
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

    @property
    def model(self) -> EmbeddingModelIdentity:
        return self._model

    @property
    def input_policy_hash(self) -> str:
        return self._policy_hash

    def embed_text(self, text: str) -> tuple[float, ...]:
        if not text or not text.strip():
            raise EmbeddingError("empty embedding text")
        # Artifact-specific tokenization is owner-supplied; this path expects a
        # pre-exported model that accepts a single string input tensor name from manifest.
        # ponytail: ceiling=string input models only; upgrade=tokenizer artifact pair
        outputs = self._session.run(None, {self._input_name: [[text]]})
        vector = tuple(float(x) for x in outputs[0].reshape(-1)[: self._dimensions])
        if len(vector) != self._dimensions:
            raise EmbeddingError("onnx output dimension mismatch")
        validate_vector(vector, dimensions=self._dimensions)
        return vector


__all__ = [
    "OfflineArtifactUnavailable",
    "OfflineOnnxEmbedder",
]
