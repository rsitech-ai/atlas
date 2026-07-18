import hashlib
import json
import os
import stat
from contextlib import suppress
from pathlib import Path
from typing import cast
from uuid import UUID

import pytest
from pydantic import ValidationError
from rsi_atlas_contracts import (
    ArtifactCommandContext,
    ArtifactID,
    ArtifactIntegrityError,
)
from rsi_atlas_storage import ContentAddressedArtifactStore

COMMAND_CONTEXT = ArtifactCommandContext(
    tenant_id=UUID("11111111-1111-1111-1111-111111111111"),
    workspace_id=UUID("22222222-2222-2222-2222-222222222222"),
    actor_id=UUID("33333333-3333-3333-3333-333333333333"),
    trace_id=UUID("44444444-4444-4444-4444-444444444444"),
)


def test_identical_bytes_reuse_one_artifact(tmp_path: Path) -> None:
    store = ContentAddressedArtifactStore(tmp_path)

    first = store.put_bytes(
        b"atlas evidence", media_type="application/octet-stream", context=COMMAND_CONTEXT
    )
    second = store.put_bytes(
        b"atlas evidence", media_type="application/octet-stream", context=COMMAND_CONTEXT
    )

    assert first == second
    assert first.artifact_id == f"sha256:{hashlib.sha256(b'atlas evidence').hexdigest()}"
    assert len(tuple(tmp_path.rglob("payload"))) == 1


def test_changed_bytes_create_a_distinct_artifact(tmp_path: Path) -> None:
    store = ContentAddressedArtifactStore(tmp_path)

    first = store.put_bytes(b"version one", media_type="application/pdf", context=COMMAND_CONTEXT)
    second = store.put_bytes(b"version two", media_type="application/pdf", context=COMMAND_CONTEXT)

    assert first.artifact_id != second.artifact_id


def test_read_rejects_modified_content(tmp_path: Path) -> None:
    store = ContentAddressedArtifactStore(tmp_path)
    artifact = store.put_bytes(b"trusted", media_type="application/pdf", context=COMMAND_CONTEXT)
    store.payload_path(artifact.artifact_id).write_bytes(b"tampered")

    with pytest.raises(ArtifactIntegrityError, match="content hash mismatch"):
        store.read_bytes(artifact.artifact_id, context=COMMAND_CONTEXT)


def test_verify_rejects_missing_manifest(tmp_path: Path) -> None:
    store = ContentAddressedArtifactStore(tmp_path)
    artifact = store.put_bytes(b"trusted", media_type="application/pdf", context=COMMAND_CONTEXT)
    store.manifest_path(artifact.artifact_id).unlink()

    with pytest.raises(ArtifactIntegrityError, match="manifest is missing"):
        store.verify(artifact.artifact_id, context=COMMAND_CONTEXT)


def test_verify_rejects_modified_manifest(tmp_path: Path) -> None:
    store = ContentAddressedArtifactStore(tmp_path)
    artifact = store.put_bytes(b"trusted", media_type="application/pdf", context=COMMAND_CONTEXT)
    store.manifest_path(artifact.artifact_id).write_text("{}")

    with pytest.raises(ArtifactIntegrityError, match="manifest hash mismatch"):
        store.verify(artifact.artifact_id, context=COMMAND_CONTEXT)


def test_verify_rejects_valid_but_modified_manifest(tmp_path: Path) -> None:
    store = ContentAddressedArtifactStore(tmp_path)
    artifact = store.put_bytes(b"trusted", media_type="application/pdf", context=COMMAND_CONTEXT)
    manifest = json.loads(store.manifest_path(artifact.artifact_id).read_text())
    manifest["media_type"] = "application/json"
    store.manifest_path(artifact.artifact_id).write_text(json.dumps(manifest))

    with pytest.raises(ArtifactIntegrityError, match="manifest hash mismatch"):
        store.verify(artifact.artifact_id, context=COMMAND_CONTEXT)


def test_invalid_artifact_identifier_cannot_escape_root(tmp_path: Path) -> None:
    store = ContentAddressedArtifactStore(tmp_path)

    with pytest.raises(ValueError, match="artifact identifier"):
        store.read_bytes(cast(ArtifactID, "sha256:../../outside"), context=COMMAND_CONTEXT)


def test_public_operations_require_command_context(tmp_path: Path) -> None:
    store = ContentAddressedArtifactStore(tmp_path)
    artifact = store.put_bytes(b"trusted", media_type="application/pdf", context=COMMAND_CONTEXT)

    with pytest.raises(TypeError, match="context"):
        store.put_bytes(b"trusted", media_type="application/pdf")
    with pytest.raises(TypeError, match="context"):
        store.read_bytes(artifact.artifact_id)
    with pytest.raises(TypeError, match="context"):
        store.verify(artifact.artifact_id)


def test_command_context_is_strict_and_immutable() -> None:
    with pytest.raises(ValidationError, match="frozen_instance"):
        COMMAND_CONTEXT.tenant_id = UUID("55555555-5555-5555-5555-555555555555")
    with pytest.raises(ValidationError, match="extra_forbidden"):
        ArtifactCommandContext.model_validate(
            {**COMMAND_CONTEXT.model_dump(), "unexpected": "value"}
        )


def test_public_operations_reject_invalid_command_context(tmp_path: Path) -> None:
    store = ContentAddressedArtifactStore(tmp_path)
    artifact = store.put_bytes(b"trusted", media_type="application/pdf", context=COMMAND_CONTEXT)
    invalid_context = cast(
        ArtifactCommandContext,
        {
            "tenant_id": "not-a-uuid",
            "workspace_id": str(COMMAND_CONTEXT.workspace_id),
            "actor_id": str(COMMAND_CONTEXT.actor_id),
            "trace_id": str(COMMAND_CONTEXT.trace_id),
        },
    )

    with pytest.raises(ValidationError, match="uuid"):
        store.put_bytes(b"trusted", media_type="application/pdf", context=invalid_context)
    with pytest.raises(ValidationError, match="uuid"):
        store.read_bytes(artifact.artifact_id, context=invalid_context)
    with pytest.raises(ValidationError, match="uuid"):
        store.verify(artifact.artifact_id, context=invalid_context)


def test_store_enforces_owner_only_permissions_for_existing_components(tmp_path: Path) -> None:
    old_umask = os.umask(0)
    try:
        root = tmp_path / "artifacts"
        root.mkdir(mode=0o777)
        (root / "sha256").mkdir(mode=0o777)
        store = ContentAddressedArtifactStore(root)
        artifact = store.put_bytes(
            b"trusted", media_type="application/pdf", context=COMMAND_CONTEXT
        )
        directory = store.payload_path(artifact.artifact_id).parent

        _assert_private_store_modes(root, directory)

        root.chmod(0o755)
        directory.chmod(0o755)
        for file_path in directory.iterdir():
            file_path.chmod(0o644)

        assert store.verify(artifact.artifact_id, context=COMMAND_CONTEXT) == artifact
        _assert_private_store_modes(root, directory)
    finally:
        os.umask(old_umask)


def test_put_rejects_symlinked_artifact_ancestor(tmp_path: Path) -> None:
    root = tmp_path / "artifacts"
    outside = tmp_path / "outside"
    root.mkdir()
    outside.mkdir()
    (root / "sha256").symlink_to(outside, target_is_directory=True)
    store = ContentAddressedArtifactStore(root)

    with pytest.raises(ArtifactIntegrityError, match="symlink"):
        store.put_bytes(b"trusted", media_type="application/pdf", context=COMMAND_CONTEXT)

    assert tuple(outside.iterdir()) == ()


def test_put_never_publishes_through_an_ancestor_swapped_after_prepare(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "artifacts"
    outside = tmp_path / "outside"
    moved = tmp_path / "moved-sha256"
    outside.mkdir()
    store = ContentAddressedArtifactStore(root)
    original_prepare = store._prepare_artifact_directory
    outside_entries_before: tuple[Path, ...] = ()
    swapped = False

    def swap_ancestor_after_prepare(artifact_id: ArtifactID) -> int:
        nonlocal outside_entries_before, swapped
        directory = original_prepare(artifact_id)
        digest = str(artifact_id).removeprefix("sha256:")
        (outside / digest[:2] / digest[2:4] / digest).mkdir(parents=True)
        outside_entries_before = tuple(outside.rglob("*"))
        (root / "sha256").rename(moved)
        (root / "sha256").symlink_to(outside, target_is_directory=True)
        swapped = True
        return directory

    monkeypatch.setattr(store, "_prepare_artifact_directory", swap_ancestor_after_prepare)

    with suppress(ArtifactIntegrityError):
        store.put_bytes(b"trusted", media_type="application/pdf", context=COMMAND_CONTEXT)

    assert swapped
    assert tuple(outside.rglob("*")) == outside_entries_before


def _assert_private_store_modes(root: Path, artifact_directory: Path) -> None:
    for directory in [root, *artifact_directory.parents[:-1], artifact_directory]:
        if directory.is_relative_to(root):
            assert stat.S_IMODE(directory.stat().st_mode) == 0o700
    for file_path in artifact_directory.iterdir():
        assert stat.S_IMODE(file_path.stat().st_mode) == 0o600
