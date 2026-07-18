import asyncio
import hashlib
import os
from pathlib import Path

import pytest
from rsi_atlas_contracts import SafetyCheckState
from rsi_atlas_engine.import_staging import ImportStagingArea, ImportStagingError
from starlette.requests import ClientDisconnect


def _private_directory(path: Path) -> Path:
    path.mkdir(mode=0o700)
    path.chmod(0o700)
    return path


async def _chunks(*payloads: bytes):
    for payload in payloads:
        yield payload


async def _disconnecting_chunks(payload: bytes):
    yield payload
    raise ClientDisconnect()


def test_async_stage_streams_to_owner_private_file_and_records_exact_evidence(
    tmp_path: Path,
) -> None:
    root = _private_directory(tmp_path / "staging")
    area = ImportStagingArea(root)
    payload = b"%PDF-1.7\n/Type /Page\nvisual evidence\n%%EOF\n"

    staged = asyncio.run(
        area.stage_chunks(
            _chunks(payload[:7], payload[7:25], payload[25:]),
            expected_bytes=len(payload),
        )
    )

    try:
        assert staged.path.read_bytes() == payload
        assert staged.evidence.digest == hashlib.sha256(payload).hexdigest()
        assert staged.evidence.size_bytes == len(payload)
        assert staged.evidence.leading_bytes == payload[:8]
        assert staged.evidence.trailing_bytes == payload[-1024:]
        assert staged.evidence.source_policy is SafetyCheckState.PASS
        assert staged.evidence.available_disk is SafetyCheckState.PASS
        assert staged.path.stat().st_mode & 0o777 == 0o600
    finally:
        staged.cleanup()

    assert tuple(root.iterdir()) == ()


@pytest.mark.parametrize("expected_bytes", (0, 33_554_433, True))
def test_async_stage_rejects_invalid_declared_size_before_writing(
    tmp_path: Path, expected_bytes: object
) -> None:
    root = _private_directory(tmp_path / "staging")
    area = ImportStagingArea(root)

    with pytest.raises((ImportStagingError, TypeError, ValueError)):
        asyncio.run(area.stage_chunks(_chunks(b"ignored"), expected_bytes=expected_bytes))

    assert tuple(root.iterdir()) == ()


def test_async_stage_rejects_actual_length_mismatch_and_cleans_up(tmp_path: Path) -> None:
    root = _private_directory(tmp_path / "staging")
    area = ImportStagingArea(root)

    with pytest.raises(ImportStagingError, match="length"):
        asyncio.run(area.stage_chunks(_chunks(b"short"), expected_bytes=10))

    assert tuple(root.iterdir()) == ()


def test_async_stage_rejects_stream_over_declared_length_and_cleans_up(tmp_path: Path) -> None:
    root = _private_directory(tmp_path / "staging")
    area = ImportStagingArea(root)

    with pytest.raises(ImportStagingError, match="length"):
        asyncio.run(area.stage_chunks(_chunks(b"too", b" many"), expected_bytes=3))

    assert tuple(root.iterdir()) == ()


def test_async_stage_cleans_partial_file_when_client_disconnects(tmp_path: Path) -> None:
    root = _private_directory(tmp_path / "staging")
    area = ImportStagingArea(root)

    with pytest.raises(ClientDisconnect):
        asyncio.run(
            area.stage_chunks(
                _disconnecting_chunks(b"%PDF-1.7\n"),
                expected_bytes=20,
            )
        )

    assert tuple(root.iterdir()) == ()


def test_stage_file_copies_without_mutating_the_selected_source(tmp_path: Path) -> None:
    root = _private_directory(tmp_path / "staging")
    source = tmp_path / "selected.pdf"
    payload = b"%PDF-1.7\nselected\n%%EOF\n"
    source.write_bytes(payload)
    source.chmod(0o644)
    before = source.stat()

    staged = ImportStagingArea(root).stage_file(source)

    try:
        assert staged.path.read_bytes() == payload
        assert source.read_bytes() == payload
        after = source.stat()
        assert (after.st_dev, after.st_ino, after.st_mode, after.st_size) == (
            before.st_dev,
            before.st_ino,
            before.st_mode,
            before.st_size,
        )
    finally:
        staged.cleanup()


@pytest.mark.parametrize("kind", ("leaf_symlink", "ancestor_symlink", "directory"))
def test_stage_file_rejects_symlink_and_non_regular_sources(tmp_path: Path, kind: str) -> None:
    root = _private_directory(tmp_path / "staging")
    target = tmp_path / "target.pdf"
    target.write_bytes(b"%PDF-1.7\n%%EOF\n")
    if kind == "leaf_symlink":
        source = tmp_path / "selected.pdf"
        source.symlink_to(target)
    elif kind == "ancestor_symlink":
        actual = _private_directory(tmp_path / "actual")
        (actual / "selected.pdf").write_bytes(target.read_bytes())
        alias = tmp_path / "alias"
        alias.symlink_to(actual, target_is_directory=True)
        source = alias / "selected.pdf"
    else:
        source = _private_directory(tmp_path / "selected.pdf")

    with pytest.raises(ImportStagingError, match="source"):
        ImportStagingArea(root).stage_file(source)

    assert tuple(root.iterdir()) == ()


def test_staging_root_must_already_be_owner_private(tmp_path: Path) -> None:
    root = tmp_path / "staging"
    root.mkdir(mode=0o755)
    root.chmod(0o755)

    with pytest.raises(ImportStagingError, match="owner-private"):
        ImportStagingArea(root)


def test_cleanup_refuses_to_unlink_a_replaced_file(tmp_path: Path) -> None:
    root = _private_directory(tmp_path / "staging")
    payload = b"%PDF-1.7\n%%EOF\n"
    staged = asyncio.run(
        ImportStagingArea(root).stage_chunks(_chunks(payload), expected_bytes=len(payload))
    )
    original = root / "original"
    staged.path.rename(original)
    staged.path.write_bytes(b"replacement")
    staged.path.chmod(0o600)

    with pytest.raises(ImportStagingError, match="changed"):
        staged.cleanup()

    assert staged.path.read_bytes() == b"replacement"
    original.unlink()
    staged.path.unlink()


def test_staging_file_names_do_not_leak_source_names(tmp_path: Path) -> None:
    root = _private_directory(tmp_path / "staging")
    source = tmp_path / "private-protocol-name.pdf"
    source.write_bytes(b"%PDF-1.7\n%%EOF\n")

    staged = ImportStagingArea(root).stage_file(source)

    try:
        assert "private-protocol-name" not in staged.path.name
    finally:
        staged.cleanup()


def test_staged_source_is_single_link_owner_private(tmp_path: Path) -> None:
    root = _private_directory(tmp_path / "staging")
    payload = b"%PDF-1.7\n%%EOF\n"
    staged = asyncio.run(
        ImportStagingArea(root).stage_chunks(_chunks(payload), expected_bytes=len(payload))
    )

    try:
        metadata = os.lstat(staged.path)
        assert metadata.st_uid == os.geteuid()
        assert metadata.st_nlink == 1
        assert metadata.st_mode & 0o777 == 0o600
    finally:
        staged.cleanup()
