import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from uuid import UUID

import pytest
from opentelemetry import trace
from rsi_atlas_observability.tracing import (
    PayloadMode,
    TraceContext,
    TracePolicyError,
    TraceRuntime,
    extract_w3c_context,
    inject_w3c_context,
)

TENANT_ID = UUID("11111111-1111-4111-8111-111111111111")
WORKSPACE_ID = UUID("22222222-2222-4222-8222-222222222222")
ACTOR_ID = UUID("33333333-3333-4333-8333-333333333333")
APPLICATION_TRACE_ID = UUID("44444444-4444-4444-8444-444444444444")


def trace_context() -> TraceContext:
    return TraceContext(
        tenant_id=TENANT_ID,
        workspace_id=WORKSPACE_ID,
        actor_id=ACTOR_ID,
        trace_id=APPLICATION_TRACE_ID,
    )


def test_local_runtime_is_metadata_only_by_default(tmp_path: Path) -> None:
    runtime = TraceRuntime.local(tmp_path / "traces.jsonl")

    assert runtime.payload_mode is PayloadMode.METADATA_ONLY
    runtime.shutdown()


def test_non_metadata_payload_modes_fail_closed(tmp_path: Path) -> None:
    with pytest.raises(TracePolicyError):
        TraceRuntime.local(tmp_path / "traces.jsonl", payload_mode=PayloadMode.DEBUG)


def test_trace_context_requires_uuid_objects() -> None:
    with pytest.raises(TracePolicyError):
        TraceContext(
            tenant_id=str(TENANT_ID),  # type: ignore[arg-type]
            workspace_id=WORKSPACE_ID,
            actor_id=ACTOR_ID,
            trace_id=APPLICATION_TRACE_ID,
        )


def test_every_supported_span_name_can_be_started(tmp_path: Path) -> None:
    runtime = TraceRuntime.local(tmp_path / "traces.jsonl")

    for name in runtime.supported_span_names:
        with runtime.start_as_current_span(name, context=trace_context()):
            pass

    runtime.shutdown()


def test_unknown_or_private_span_names_fail_before_collection(tmp_path: Path) -> None:
    runtime = TraceRuntime.local(tmp_path / "traces.jsonl")

    with pytest.raises(TracePolicyError):
        runtime.start_as_current_span("atlas.document.private", context=trace_context())
    with pytest.raises(TracePolicyError):
        runtime.start_as_current_span("atlas.command", context=None)  # type: ignore[arg-type]

    runtime.shutdown()


def test_local_runtime_writes_compact_deterministic_metadata(tmp_path: Path) -> None:
    destination = tmp_path / "traces.jsonl"
    runtime = TraceRuntime.local(destination)

    with runtime.start_as_current_span("atlas.command", context=trace_context()) as span:
        span.set_attribute("atlas.command.name", "Doctor")
        span.set_attribute("atlas.count", 3)
        span.set_status_error()
    runtime.shutdown()

    record = json.loads(destination.read_text(encoding="utf-8"))
    assert record["schema_version"] == "1.0.0"
    assert record["name"] == "atlas.command"
    assert record["context"]["tenant_id"] == str(TENANT_ID)
    assert record["attributes"] == {"atlas.command.name": "Doctor", "atlas.count": 3}
    assert len(record["trace_id"]) == 32
    assert len(record["span_id"]) == 16
    assert record["status_code"] == "ERROR"


def test_runtimes_are_isolated_and_do_not_replace_global_provider(tmp_path: Path) -> None:
    global_provider = trace.get_tracer_provider()
    first = TraceRuntime.local(tmp_path / "first.jsonl")
    second = TraceRuntime.local(tmp_path / "second.jsonl")

    assert first.provider is not second.provider
    assert trace.get_tracer_provider() is global_provider
    assert first.export_destinations == (tmp_path / "first.jsonl",)

    first.shutdown()
    second.shutdown()


def test_w3c_helpers_allow_only_trace_headers(tmp_path: Path) -> None:
    runtime = TraceRuntime.local(tmp_path / "traces.jsonl")
    with runtime.start_as_current_span("atlas.command", context=trace_context()) as span:
        carrier = inject_w3c_context(span)

    extracted = extract_w3c_context(carrier)
    assert extracted.traceparent == carrier["traceparent"]
    assert "tracestate" not in carrier

    with pytest.raises(TracePolicyError):
        extract_w3c_context({"traceparent": carrier["traceparent"], "payload": "private"})
    with pytest.raises(TracePolicyError):
        inject_w3c_context(span, tracestate="tenant=private")
    with pytest.raises(TracePolicyError):
        extract_w3c_context({"traceparent": carrier["traceparent"], "tracestate": "tenant=private"})
    with pytest.raises(TracePolicyError):
        extract_w3c_context({"traceparent": "00-" + "0" * 32 + "-" + "1" * 16 + "-01"})
    runtime.shutdown()


def test_safe_span_never_records_exception_message_or_stack(tmp_path: Path) -> None:
    destination = tmp_path / "traces.jsonl"
    runtime = TraceRuntime.local(destination)

    with (
        pytest.raises(RuntimeError, match="private"),
        runtime.start_as_current_span("atlas.command", context=trace_context()),
    ):
        raise RuntimeError("private exception payload")
    runtime.shutdown()

    record = json.loads(destination.read_text(encoding="utf-8"))
    assert record["status_code"] == "ERROR"
    assert record["attributes"]["atlas.error.code"] == "unhandled"
    assert "private exception payload" not in destination.read_text(encoding="utf-8")
    assert "exception" not in record


def test_raw_sdk_bypass_cannot_persist_unsafe_attributes_or_events(tmp_path: Path) -> None:
    destination = tmp_path / "traces.jsonl"
    runtime = TraceRuntime.local(destination)
    raw_span = runtime.provider.get_tracer("bypass").start_span(
        "atlas.command",
        attributes={
            **trace_context().attributes(),
            "document.text": "private",
        },
    )
    raw_span.add_event("private-event")
    raw_span.end()
    runtime.shutdown()

    assert destination.read_bytes() == b""


def test_reopen_appends_only_canonical_records(tmp_path: Path) -> None:
    destination = tmp_path / "traces.jsonl"
    for command_name in ("Doctor", "Validate"):
        runtime = TraceRuntime.local(destination)
        with runtime.start_as_current_span("atlas.command", context=trace_context()) as span:
            span.set_attribute("atlas.command.name", command_name)
        runtime.shutdown()

    records = [json.loads(line) for line in destination.read_text(encoding="utf-8").splitlines()]
    command_names = [record["attributes"]["atlas.command.name"] for record in records]
    assert command_names == ["Doctor", "Validate"]


def test_threaded_runtimes_append_complete_records(tmp_path: Path) -> None:
    destination = tmp_path / "traces.jsonl"

    def write_one(_: int) -> None:
        runtime = TraceRuntime.local(destination)
        with runtime.start_as_current_span("atlas.command", context=trace_context()) as span:
            span.set_attribute("atlas.command.name", "Doctor")
        runtime.shutdown()

    with ThreadPoolExecutor(max_workers=4) as executor:
        list(executor.map(write_one, range(12)))

    records = [json.loads(line) for line in destination.read_text(encoding="utf-8").splitlines()]
    assert len(records) == 12
