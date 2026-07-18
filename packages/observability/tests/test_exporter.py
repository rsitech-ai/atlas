import json
import multiprocessing
import os
import stat
import threading
import traceback
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID

import pytest
import rsi_atlas_observability.exporter as exporter_module
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace.export import SpanExportResult
from opentelemetry.trace import Status, StatusCode
from rsi_atlas_observability.exporter import LocalJSONLSpanExporter, TraceStorageError
from rsi_atlas_observability.tracing import TraceContext, TraceRuntime


def _trace_context() -> TraceContext:
    return TraceContext(
        tenant_id=UUID("11111111-1111-4111-8111-111111111111"),
        workspace_id=UUID("22222222-2222-4222-8222-222222222222"),
        actor_id=UUID("33333333-3333-4333-8333-333333333333"),
        trace_id=UUID("44444444-4444-4444-8444-444444444444"),
    )


def _write_trace_process(destination: str, start: object, result: object) -> None:
    try:
        start.wait(10)  # type: ignore[attr-defined]
        runtime = TraceRuntime.local(Path(destination))
        for _ in range(8):
            with runtime.start_as_current_span("atlas.command", context=_trace_context()):
                pass
        runtime.shutdown()
        result.put(None)  # type: ignore[attr-defined]
    except BaseException as error:
        cause = error.__cause__
        frames = traceback.extract_tb(cause.__traceback__) if cause is not None else []
        diagnostic = (
            type(error).__name__,
            type(cause).__name__ if cause is not None else None,
            getattr(cause, "errno", None),
            (frames[-1].name, frames[-1].lineno) if frames else None,
        )
        result.put(diagnostic)  # type: ignore[attr-defined]


def _hold_trace_file_lock(destination: str, ready: object, release: object) -> None:
    exporter = LocalJSONLSpanExporter(Path(destination))
    fcntl = exporter_module.fcntl
    fcntl.flock(exporter._file_fd, fcntl.LOCK_EX)
    ready.set()  # type: ignore[attr-defined]
    release.wait(10)  # type: ignore[attr-defined]
    fcntl.flock(exporter._file_fd, fcntl.LOCK_UN)
    exporter.shutdown()


def _open_trace_file(destination: str, attempted: object, opened: object) -> None:
    attempted.set()  # type: ignore[attr-defined]
    exporter = LocalJSONLSpanExporter(Path(destination))
    opened.set()  # type: ignore[attr-defined]
    exporter.shutdown()


def _fake_span(*, trace_id: int, span_id: int) -> object:
    context = _trace_context().attributes()
    return SimpleNamespace(
        resource=Resource.get_empty(),
        events=(),
        links=(),
        status=Status(StatusCode.UNSET),
        name="atlas.command",
        attributes=context,
        get_span_context=lambda: SimpleNamespace(trace_id=trace_id, span_id=span_id),
        parent=None,
        start_time=1,
        end_time=2,
    )


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
    assert calls == [
        exporter_module.fcntl.LOCK_EX | exporter_module.fcntl.LOCK_NB,
        exporter_module.fcntl.LOCK_UN,
    ]
    exporter.shutdown()


def test_existing_zero_identifier_record_fails_closed(tmp_path: Path) -> None:
    destination = tmp_path / "traces.jsonl"
    record = {
        "schema_version": "1.0.0",
        "name": "atlas.command",
        "context": {
            "tenant_id": "11111111-1111-4111-8111-111111111111",
            "workspace_id": "22222222-2222-4222-8222-222222222222",
            "actor_id": "33333333-3333-4333-8333-333333333333",
            "trace_id": "44444444-4444-4444-8444-444444444444",
        },
        "attributes": {},
        "trace_id": "0" * 32,
        "span_id": "1" * 16,
        "parent_span_id": None,
        "start_time_unix_nano": 1,
        "end_time_unix_nano": 2,
        "duration_ns": 1,
        "status_code": "UNSET",
    }
    destination.write_text(json.dumps(record, sort_keys=True, separators=(",", ":")) + "\n")
    destination.chmod(0o600)
    with pytest.raises(TraceStorageError):
        LocalJSONLSpanExporter(destination)


def test_partial_write_permanently_prevents_later_append(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    destination = tmp_path / "traces.jsonl"
    runtime = TraceRuntime.local(destination)
    original_write = exporter_module.os.write
    partial_prefix: bytes | None = None

    def write_prefix_then_fail(descriptor: int, payload: object) -> int:
        nonlocal partial_prefix
        if partial_prefix is None:
            partial_prefix = bytes(payload)[:13]  # type: ignore[arg-type]
            original_write(descriptor, partial_prefix)
            raise OSError("synthetic partial write")
        return original_write(descriptor, payload)  # type: ignore[arg-type]

    monkeypatch.setattr(exporter_module.os, "write", write_prefix_then_fail)
    with runtime.start_as_current_span("atlas.command", context=_trace_context()):
        pass
    monkeypatch.setattr(exporter_module.os, "write", original_write)

    assert partial_prefix is not None
    corrupted_prefix = destination.read_bytes()
    assert corrupted_prefix == partial_prefix
    assert runtime.force_flush() is False

    with runtime.start_as_current_span("atlas.command", context=_trace_context()):
        pass
    runtime.shutdown()

    assert destination.read_bytes() == corrupted_prefix


@pytest.mark.parametrize(
    ("trace_id", "span_id"),
    [
        (0, 1),
        (-1, 1),
        (1 << 128, 1),
        (1, 0),
        (1, -1),
        (1, 1 << 64),
    ],
)
def test_raw_export_rejects_noncanonical_sdk_identifiers(
    tmp_path: Path,
    trace_id: int,
    span_id: int,
) -> None:
    destination = tmp_path / f"{trace_id}-{span_id}.jsonl"
    exporter = LocalJSONLSpanExporter(destination)

    result = exporter.export((_fake_span(trace_id=trace_id, span_id=span_id),))  # type: ignore[arg-type]

    assert result is SpanExportResult.FAILURE
    assert destination.read_bytes() == b""
    exporter.shutdown()


def test_capacity_is_rechecked_after_each_cross_process_lock(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    destination = tmp_path / "traces.jsonl"
    first = LocalJSONLSpanExporter(destination)
    second = LocalJSONLSpanExporter(destination)
    payload = b"x" * 60
    barrier = threading.Barrier(2)
    original_flock = exporter_module.fcntl.flock

    monkeypatch.setattr(exporter_module, "_MAX_FILE_BYTES", 100)
    monkeypatch.setattr(first, "_span_record", lambda span: {})
    monkeypatch.setattr(second, "_span_record", lambda span: {})
    monkeypatch.setattr(first, "_encode_record", lambda record: payload)
    monkeypatch.setattr(second, "_encode_record", lambda record: payload)

    def synchronized_flock(descriptor: int, operation: int) -> None:
        if operation == exporter_module.fcntl.LOCK_EX:
            barrier.wait(timeout=5)
        original_flock(descriptor, operation)

    monkeypatch.setattr(exporter_module.fcntl, "flock", synchronized_flock)
    results: list[SpanExportResult] = []

    def export_one(exporter: LocalJSONLSpanExporter) -> None:
        results.append(exporter.export((object(),)))  # type: ignore[arg-type]

    threads = [
        threading.Thread(target=export_one, args=(candidate,)) for candidate in (first, second)
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=5)

    assert all(not thread.is_alive() for thread in threads)
    assert sorted(result.name for result in results) == ["FAILURE", "SUCCESS"]
    assert destination.stat().st_size == len(payload)
    first.shutdown()
    second.shutdown()


def test_processes_append_complete_json_records(tmp_path: Path) -> None:
    destination = tmp_path / "traces.jsonl"
    context = multiprocessing.get_context("spawn")
    start = context.Event()
    result = context.Queue()
    processes = [
        context.Process(target=_write_trace_process, args=(str(destination), start, result))
        for _ in range(3)
    ]

    for process in processes:
        process.start()
    start.set()
    for process in processes:
        process.join(timeout=20)

    assert all(process.exitcode == 0 for process in processes)
    assert [result.get(timeout=2) for _ in processes] == [None, None, None]
    records = [json.loads(line) for line in destination.read_text(encoding="utf-8").splitlines()]
    assert len(records) == 24


def test_process_initialization_waits_for_existing_file_lock(tmp_path: Path) -> None:
    destination = tmp_path / "traces.jsonl"
    context = multiprocessing.get_context("spawn")
    ready = context.Event()
    release = context.Event()
    attempted = context.Event()
    opened = context.Event()
    holder = context.Process(
        target=_hold_trace_file_lock,
        args=(str(destination), ready, release),
    )
    opener = context.Process(
        target=_open_trace_file,
        args=(str(destination), attempted, opened),
    )

    holder.start()
    assert ready.wait(10)
    opener.start()
    assert attempted.wait(10)
    assert opened.wait(0.25) is False
    release.set()
    assert opened.wait(10)
    holder.join(timeout=10)
    opener.join(timeout=10)

    assert holder.exitcode == 0
    assert opener.exitcode == 0
