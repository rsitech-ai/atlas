import os
import stat
from pathlib import Path

import pytest
import rsi_atlas_observability.exporter as exporter_module
from rsi_atlas_observability.exporter import LocalJSONLSpanExporter, TraceStorageError
from rsi_atlas_observability.tracing import TraceRuntime


def test_existing_malformed_jsonl_fails_closed(tmp_path: Path) -> None:
    destination = tmp_path / "traces.jsonl"
    destination.write_text('{"not":"canonical"}', encoding="utf-8")
    destination.chmod(0o600)

    with pytest.raises(TraceStorageError, match="existing trace storage is invalid"):
        TraceRuntime.local(destination)


def test_storage_requires_private_parent_and_regular_private_file(tmp_path: Path) -> None:
    destination = tmp_path / "traces.jsonl"
    tmp_path.chmod(0o755)
    with pytest.raises(TraceStorageError):
        LocalJSONLSpanExporter(destination)


def test_symlink_and_hard_link_destinations_fail_closed(tmp_path: Path) -> None:
    source = tmp_path / "source.jsonl"
    source.write_text("", encoding="utf-8")
    source.chmod(0o600)
    symlink = tmp_path / "symlink.jsonl"
    symlink.symlink_to(source)
    hard_link = tmp_path / "hard.jsonl"
    os.link(source, hard_link)

    with pytest.raises(TraceStorageError):
        LocalJSONLSpanExporter(symlink)
    with pytest.raises(TraceStorageError):
        LocalJSONLSpanExporter(hard_link)


def test_export_after_shutdown_fails_deterministically(tmp_path: Path) -> None:
    exporter = LocalJSONLSpanExporter(tmp_path / "traces.jsonl")
    exporter.shutdown()

    assert exporter.export(()) is not None
    assert exporter.force_flush() is False


def test_destination_created_with_private_mode(tmp_path: Path) -> None:
    destination = tmp_path / "traces.jsonl"
    exporter = LocalJSONLSpanExporter(destination)

    assert stat.S_IMODE(destination.stat().st_mode) == 0o600
    exporter.shutdown()


def test_fifo_and_destination_replacement_fail_closed(tmp_path: Path) -> None:
    fifo = tmp_path / "trace.fifo"
    os.mkfifo(fifo, 0o600)
    with pytest.raises(TraceStorageError):
        LocalJSONLSpanExporter(fifo)

    destination = tmp_path / "traces.jsonl"
    exporter = LocalJSONLSpanExporter(destination)
    destination.unlink()
    destination.write_text("", encoding="utf-8")
    destination.chmod(0o600)

    assert exporter.force_flush() is False
    exporter.shutdown()


def test_force_flush_uses_the_cross_process_file_lock(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    exporter = LocalJSONLSpanExporter(tmp_path / "traces.jsonl")
    calls: list[int] = []
    original_flock = exporter_module.fcntl.flock

    def record_flock(descriptor: int, operation: int) -> None:
        calls.append(operation)
        original_flock(descriptor, operation)

    monkeypatch.setattr(exporter_module.fcntl, "flock", record_flock)

    assert exporter.force_flush() is True
    assert calls == [exporter_module.fcntl.LOCK_EX, exporter_module.fcntl.LOCK_UN]
    exporter.shutdown()
