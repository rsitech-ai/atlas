"""Isolated OpenTelemetry tracing facade with a metadata-only collection gate."""

from __future__ import annotations

import re
from collections.abc import Mapping
from contextlib import AbstractContextManager
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from types import TracebackType
from typing import Final, Self
from uuid import UUID

from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.trace import Span as SDKSpan
from opentelemetry.trace import Status, StatusCode, Tracer

from rsi_atlas_observability.exporter import LocalJSONLSpanExporter
from rsi_atlas_observability.redaction import (
    SUPPORTED_SPAN_NAMES,
    TracePolicyError,
    validate_attribute,
    validate_span_name,
    validate_uuid,
)


class PayloadMode(StrEnum):
    METADATA_ONLY = "metadata_only"
    STANDARD = "standard"
    DEBUG = "debug"
    EVALUATION = "evaluation"


@dataclass(frozen=True, slots=True)
class TraceContext:
    """Immutable application identity required for every collected span."""

    tenant_id: UUID
    workspace_id: UUID
    actor_id: UUID
    trace_id: UUID

    def __post_init__(self) -> None:
        for value in (self.tenant_id, self.workspace_id, self.actor_id, self.trace_id):
            if type(value) is not UUID:
                raise TracePolicyError("trace context identifiers must be UUID objects")
            validate_uuid(value)

    def attributes(self) -> dict[str, str]:
        return {
            "atlas.tenant.id": str(self.tenant_id),
            "atlas.workspace.id": str(self.workspace_id),
            "atlas.actor.id": str(self.actor_id),
            "atlas.application_trace.id": str(self.trace_id),
        }


@dataclass(frozen=True, slots=True)
class W3CTraceContext:
    traceparent: str
    tracestate: str | None = None


_TRACEPARENT = re.compile(r"^00-([0-9a-f]{32})-([0-9a-f]{16})-([01]{2})$")


def _validate_traceparent(value: object) -> str:
    if type(value) is not str or len(value) != 55:
        raise TracePolicyError("traceparent is invalid")
    match = _TRACEPARENT.fullmatch(value)
    if match is None or match.group(1) == "0" * 32 or match.group(2) == "0" * 16:
        raise TracePolicyError("traceparent is invalid")
    return value


def inject_w3c_context(span: SafeSpan, *, tracestate: str | None = None) -> dict[str, str]:
    """Emit only bounded W3C headers for an already-started safe span."""

    span_context = span._require_span().get_span_context()
    sampled_flag = "01" if span_context.trace_flags.sampled else "00"
    traceparent = f"00-{span_context.trace_id:032x}-{span_context.span_id:016x}-{sampled_flag}"
    result = {"traceparent": _validate_traceparent(traceparent)}
    if tracestate is not None:
        raise TracePolicyError("tracestate is unavailable in metadata-only mode")
    return result


def extract_w3c_context(carrier: Mapping[str, str]) -> W3CTraceContext:
    """Validate a strict two-header carrier without accepting application data."""

    if set(carrier) - {"traceparent", "tracestate"} or "traceparent" not in carrier:
        raise TracePolicyError("trace carrier contains unsupported headers")
    traceparent = _validate_traceparent(carrier["traceparent"])
    if "tracestate" in carrier:
        raise TracePolicyError("tracestate is unavailable in metadata-only mode")
    tracestate = None
    return W3CTraceContext(traceparent=traceparent, tracestate=tracestate)


class SafeSpan(AbstractContextManager["SafeSpan"]):
    """A deliberately narrow facade around an SDK span."""

    def __init__(self, context_manager: AbstractContextManager[SDKSpan]) -> None:
        self._context_manager = context_manager
        self._span: SDKSpan | None = None

    def __enter__(self) -> Self:
        self._span = self._context_manager.__enter__()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> bool | None:
        if self._span is not None and exc_type is not None:
            self._require_span().set_attribute("atlas.error.code", "unhandled")
            self.set_status_error()
        return self._context_manager.__exit__(exc_type, exc_value, traceback)

    def set_attribute(self, name: str, value: object) -> None:
        validated = validate_attribute(name, value)
        self._require_span().set_attribute(name, validated)

    def set_status_error(self) -> None:
        self._require_span().set_status(Status(StatusCode.ERROR))

    def set_error_code(self, code: str) -> None:
        self._require_span().set_attribute(
            "atlas.error.code", validate_attribute("atlas.error.code", code)
        )
        self.set_status_error()

    def add_event(self, *args: object, **kwargs: object) -> None:
        del args, kwargs
        raise TracePolicyError("trace events are disabled")

    def record_exception(self, *args: object, **kwargs: object) -> None:
        del args, kwargs
        raise TracePolicyError("trace exception recording is disabled")

    def set_status(self, status: object, description: object | None = None) -> None:
        del status, description
        raise TracePolicyError("trace status descriptions are disabled")

    def _require_span(self) -> SDKSpan:
        if self._span is None:
            raise TracePolicyError("trace span is not active")
        return self._span


class TraceRuntime:
    """Owns a private provider and local-only exporter without global mutation."""

    def __init__(
        self,
        provider: TracerProvider,
        exporter: LocalJSONLSpanExporter,
        tracer: Tracer,
    ) -> None:
        self._provider = provider
        self._exporter = exporter
        self._tracer = tracer
        self._shutdown = False
        self.payload_mode = PayloadMode.METADATA_ONLY

    @classmethod
    def local(
        cls,
        destination: Path,
        *,
        payload_mode: PayloadMode = PayloadMode.METADATA_ONLY,
    ) -> Self:
        if payload_mode is not PayloadMode.METADATA_ONLY:
            raise TracePolicyError("payload mode is not available in phase 1")
        exporter = LocalJSONLSpanExporter(destination)
        provider = TracerProvider(resource=Resource.get_empty(), shutdown_on_exit=False)
        provider.add_span_processor(SimpleSpanProcessor(exporter))
        tracer = provider.get_tracer("rsi_atlas_observability", "1.0.0")
        return cls(provider, exporter, tracer)

    @property
    def provider(self) -> TracerProvider:
        return self._provider

    @property
    def export_destinations(self) -> tuple[Path, ...]:
        return (self._exporter.destination,)

    @property
    def supported_span_names(self) -> tuple[str, ...]:
        return tuple(sorted(SUPPORTED_SPAN_NAMES))

    def start_as_current_span(self, name: str, *, context: TraceContext) -> SafeSpan:
        if self._shutdown:
            raise TracePolicyError("trace runtime is shut down")
        span_name = validate_span_name(name)
        if not isinstance(context, TraceContext):
            raise TracePolicyError("trace context is required")
        manager = self._tracer.start_as_current_span(
            span_name,
            attributes=context.attributes(),
            record_exception=False,
            set_status_on_exception=False,
        )
        return SafeSpan(manager)

    def force_flush(self) -> bool:
        if self._shutdown:
            return False
        return self._exporter.force_flush()

    def shutdown(self) -> None:
        if self._shutdown:
            return
        self._shutdown = True
        self._provider.shutdown()


__all__: Final = [
    "PayloadMode",
    "SafeSpan",
    "TraceContext",
    "TracePolicyError",
    "TraceRuntime",
    "W3CTraceContext",
    "extract_w3c_context",
    "inject_w3c_context",
]
