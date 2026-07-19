"""Link a Swift command traceparent through publication (metadata-only local spans)."""

from __future__ import annotations

from pathlib import Path
from uuid import UUID

from rsi_atlas_observability.tracing import (
    TraceContext,
    TraceRuntime,
    extract_w3c_context,
    inject_w3c_context,
)


def record_swift_to_publication_trace(
    *,
    destination: Path,
    tenant_id: UUID,
    workspace_id: UUID,
    actor_id: UUID,
    trace_id: UUID,
    artifact_sha256: str,
) -> str:
    """Create atlas.command → atlas.publish spans and return child traceparent.

    ponytail: ceiling=local JSONL only (no Swift process join yet); upgrade=native
    OTel exporter in RSIAtlasCore forwarding the same trace_id.
    """
    if len(artifact_sha256) != 64:
        raise ValueError("artifact_sha256 must be 64 hex chars")
    runtime = TraceRuntime.local(destination)
    context = TraceContext(
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        actor_id=actor_id,
        trace_id=trace_id,
    )
    try:
        with runtime.start_as_current_span("atlas.command", context=context) as command:
            command.set_attribute("atlas.command.name", "Publish")
            headers = inject_w3c_context(command)
            extract_w3c_context(headers)
            with runtime.start_as_current_span("atlas.publish", context=context) as pub:
                pub.set_attribute("atlas.artifact.sha256", artifact_sha256)
                pub.set_attribute("atlas.outcome", "success")
                child = inject_w3c_context(pub)
        runtime.force_flush()
        return child["traceparent"]
    finally:
        runtime.shutdown()


__all__ = ["record_swift_to_publication_trace"]
