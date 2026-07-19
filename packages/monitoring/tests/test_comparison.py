"""Comparison matrix and timeline builder tests."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from rsi_atlas_collectors import import_fixture
from rsi_atlas_contracts import ArtifactCommandContext, ComparisonAxis, TimelineEventKind
from rsi_atlas_monitoring import build_comparison_matrix, build_cross_chain_timeline

TENANT_ID = UUID("00000000-0000-4000-8000-000000000001")
WORKSPACE_ID = UUID("00000000-0000-4000-8000-000000000002")
ACTOR_ID = UUID("00000000-0000-4000-8000-000000000003")
TRACE_ID = UUID("00000000-0000-4000-8000-000000000004")
NOW = datetime(2026, 7, 19, 12, 0, tzinfo=UTC)


def _context() -> ArtifactCommandContext:
    return ArtifactCommandContext(
        tenant_id=TENANT_ID,
        workspace_id=WORKSPACE_ID,
        actor_id=ACTOR_ID,
        trace_id=TRACE_ID,
    )


def test_comparison_matrix_links_envelope_ids() -> None:
    context = _context()
    btc = import_fixture(context=context, fixture_name="bitcoin_block.json", now=NOW)
    evm = import_fixture(context=context, fixture_name="evm_block.json", now=NOW)
    assert btc.observation is not None
    assert evm.observation is not None
    matrix = build_comparison_matrix(
        context=context,
        observations=(btc.observation, evm.observation),
        axes=(ComparisonAxis.SOURCE_FAMILY, ComparisonAxis.QUALITY),
        as_of=NOW,
    )
    assert matrix.cells
    assert all(cell.envelope_id.startswith("envelope:") for cell in matrix.cells)
    assert "asset:btc" in matrix.subjects or any("btc" in subject for subject in matrix.subjects)


def test_timeline_includes_observation_events() -> None:
    context = _context()
    btc = import_fixture(context=context, fixture_name="bitcoin_block.json", now=NOW)
    sol = import_fixture(context=context, fixture_name="solana_slot.json", now=NOW)
    assert btc.observation is not None
    assert sol.observation is not None
    timeline = build_cross_chain_timeline(
        context=context,
        observations=(btc.observation, sol.observation),
        as_of=NOW,
    )
    assert len(timeline.events) == 2
    assert all(event.event_kind is TimelineEventKind.OBSERVATION for event in timeline.events)
    assert all(event.observation_id is not None for event in timeline.events)
    assert all(event.envelope_id is not None for event in timeline.events)
