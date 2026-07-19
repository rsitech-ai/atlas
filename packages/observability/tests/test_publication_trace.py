"""Swift→publication local trace bridge tests."""

from __future__ import annotations

from pathlib import Path
from uuid import UUID

from rsi_atlas_observability.publication_trace import record_swift_to_publication_trace

TENANT = UUID("00000000-0000-4000-8000-000000000001")
WORKSPACE = UUID("00000000-0000-4000-8000-000000000002")
ACTOR = UUID("00000000-0000-4000-8000-000000000003")
TRACE = UUID("00000000-0000-4000-8000-000000000004")


def test_swift_to_publication_writes_jsonl(tmp_path: Path) -> None:
    dest = tmp_path / "traces.jsonl"
    parent = record_swift_to_publication_trace(
        destination=dest,
        tenant_id=TENANT,
        workspace_id=WORKSPACE,
        actor_id=ACTOR,
        trace_id=TRACE,
        artifact_sha256="a" * 64,
    )
    assert parent.startswith("00-")
    assert dest.is_file()
    assert dest.stat().st_size > 0
