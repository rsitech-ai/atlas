"""Privacy-safe, local-only observability primitives for RSI Atlas."""

from rsi_atlas_observability.exporter import LocalJSONLSpanExporter, TraceStorageError
from rsi_atlas_observability.redaction import SensitiveTraceAttributeError
from rsi_atlas_observability.tracing import (
    PayloadMode,
    SafeSpan,
    TraceContext,
    TracePolicyError,
    TraceRuntime,
    W3CTraceContext,
    extract_w3c_context,
    inject_w3c_context,
)

__all__ = [
    "LocalJSONLSpanExporter",
    "PayloadMode",
    "SafeSpan",
    "SensitiveTraceAttributeError",
    "TraceContext",
    "TracePolicyError",
    "TraceRuntime",
    "TraceStorageError",
    "W3CTraceContext",
    "extract_w3c_context",
    "inject_w3c_context",
]
