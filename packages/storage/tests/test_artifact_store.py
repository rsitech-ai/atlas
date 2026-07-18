import hashlib
import json
from pathlib import Path
from typing import cast

import pytest
from rsi_atlas_contracts import ArtifactID, ArtifactIntegrityError
from rsi_atlas_storage import ContentAddressedArtifactStore


def test_identical_bytes_reuse_one_artifact(tmp_path: Path) -> None:
    store = ContentAddressedArtifactStore(tmp_path)

    first = store.put_bytes(b"atlas evidence", media_type="application/octet-stream")
    second = store.put_bytes(b"atlas evidence", media_type="application/octet-stream")

    assert first == second
    assert first.artifact_id == f"sha256:{hashlib.sha256(b'atlas evidence').hexdigest()}"
    assert len(tuple(tmp_path.rglob("payload"))) == 1


def test_changed_bytes_create_a_distinct_artifact(tmp_path: Path) -> None:
    store = ContentAddressedArtifactStore(tmp_path)

    first = store.put_bytes(b"version one", media_type="application/pdf")
    second = store.put_bytes(b"version two", media_type="application/pdf")

    assert first.artifact_id != second.artifact_id


def test_read_rejects_modified_content(tmp_path: Path) -> None:
    store = ContentAddressedArtifactStore(tmp_path)
    artifact = store.put_bytes(b"trusted", media_type="application/pdf")
    store.payload_path(artifact.artifact_id).write_bytes(b"tampered")

    with pytest.raises(ArtifactIntegrityError, match="content hash mismatch"):
        store.read_bytes(artifact.artifact_id)


def test_verify_rejects_missing_manifest(tmp_path: Path) -> None:
    store = ContentAddressedArtifactStore(tmp_path)
    artifact = store.put_bytes(b"trusted", media_type="application/pdf")
    store.manifest_path(artifact.artifact_id).unlink()

    with pytest.raises(ArtifactIntegrityError, match="manifest is missing"):
        store.verify(artifact.artifact_id)


def test_verify_rejects_modified_manifest(tmp_path: Path) -> None:
    store = ContentAddressedArtifactStore(tmp_path)
    artifact = store.put_bytes(b"trusted", media_type="application/pdf")
    store.manifest_path(artifact.artifact_id).write_text("{}")

    with pytest.raises(ArtifactIntegrityError, match="manifest hash mismatch"):
        store.verify(artifact.artifact_id)


def test_verify_rejects_valid_but_modified_manifest(tmp_path: Path) -> None:
    store = ContentAddressedArtifactStore(tmp_path)
    artifact = store.put_bytes(b"trusted", media_type="application/pdf")
    manifest = json.loads(store.manifest_path(artifact.artifact_id).read_text())
    manifest["media_type"] = "application/json"
    store.manifest_path(artifact.artifact_id).write_text(json.dumps(manifest))

    with pytest.raises(ArtifactIntegrityError, match="manifest hash mismatch"):
        store.verify(artifact.artifact_id)


def test_invalid_artifact_identifier_cannot_escape_root(tmp_path: Path) -> None:
    store = ContentAddressedArtifactStore(tmp_path)

    with pytest.raises(ValueError, match="artifact identifier"):
        store.read_bytes(cast(ArtifactID, "sha256:../../outside"))
