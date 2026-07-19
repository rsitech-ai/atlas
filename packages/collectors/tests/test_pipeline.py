"""Offline fixture collector pipeline tests."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest
from rsi_atlas_collectors import (
    AnalyticsBackendBlocked,
    FeatureLeakageError,
    LiveCollectorBlocked,
    MarketSequenceError,
    QualityQuarantine,
    analytics_gates,
    compute_btc_fee_regime,
    detect_fee_regime_signal,
    import_fixture,
    mark_orphaned,
    refuse_live_collect,
    require_contiguous_sequence,
    require_postgres_only,
)
from rsi_atlas_contracts import (
    AcquisitionMode,
    AnalyticsBackend,
    ArtifactCommandContext,
    FinalityState,
    GitHubRecord,
    GovernanceRecord,
    InstrumentIdentity,
    MarketTick,
    ObservationQuality,
    ProviderQualityState,
    SourceFamily,
)

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


@pytest.mark.parametrize(
    "fixture_name,family",
    [
        ("bitcoin_block.json", SourceFamily.BITCOIN),
        ("evm_block.json", SourceFamily.EVM),
        ("solana_slot.json", SourceFamily.SOLANA),
        ("market_tick.json", SourceFamily.MARKET),
        ("governance_proposal.json", SourceFamily.GOVERNANCE),
        ("github_release.json", SourceFamily.GITHUB),
    ],
)
def test_fixture_import_yields_envelope_and_observation(
    fixture_name: str, family: SourceFamily
) -> None:
    result = import_fixture(context=_context(), fixture_name=fixture_name, now=NOW)
    assert result.envelope.source_family is family
    assert result.envelope.network_policy_decision == "allow_offline"
    assert result.quarantine is None
    assert result.observation is not None
    assert result.observation.header.source_family is family
    assert result.observation.header.envelope_id == result.envelope.envelope_id
    if family in {SourceFamily.BITCOIN, SourceFamily.EVM, SourceFamily.SOLANA}:
        assert result.observation.header.chain_pin is not None


def test_live_collectors_fail_closed() -> None:
    with pytest.raises(LiveCollectorBlocked, match="blocked_live_network"):
        refuse_live_collect(family=SourceFamily.EVM, mode=AcquisitionMode.SNAPSHOT)


def test_conflicted_provider_quarantines() -> None:
    result = import_fixture(
        context=_context(),
        fixture_name="evm_block.json",
        now=NOW,
        provider_quality=ProviderQualityState.CONFLICTED,
    )
    assert result.observation is None
    assert result.quarantine is not None
    assert "provider_disagreement_conflicted" in result.quarantine.reasons


def test_governance_links_on_chain_and_off_chain() -> None:
    result = import_fixture(context=_context(), fixture_name="governance_proposal.json", now=NOW)
    assert result.observation is not None
    payload = result.observation.payload
    assert isinstance(payload, GovernanceRecord)
    assert payload.on_chain_execution_id == "0xexecdeadbeef"
    assert payload.off_chain_discussion_id == "forum:42"


def test_github_preserves_cursor_and_rate_limit() -> None:
    result = import_fixture(context=_context(), fixture_name="github_release.json", now=NOW)
    assert result.observation is not None
    payload = result.observation.payload
    assert isinstance(payload, GitHubRecord)
    assert payload.cursor == "page:1"
    assert payload.rate_limit_remaining == 58


def test_market_sequence_gap_forces_resnapshot() -> None:
    instrument = InstrumentIdentity(
        venue="fixture",
        venue_symbol="BTC-USD",
        base="BTC",
        quote="USD",
        instrument_type="spot",
        tick_size="0.01",
        quantity_step="0.0001",
        multiplier="1",
    )
    previous = MarketTick(
        instrument=instrument,
        sequence=1,
        bid="1.00",
        ask="1.01",
        last="1.00",
        bid_size="1",
        ask_size="1",
        exchange_event_time=NOW,
    )
    current = MarketTick(
        instrument=instrument,
        sequence=3,
        bid="1.00",
        ask="1.01",
        last="1.00",
        bid_size="1",
        ask_size="1",
        exchange_event_time=NOW,
    )
    with pytest.raises(MarketSequenceError, match="resnapshot"):
        require_contiguous_sequence(previous=previous, current=current)


def test_feature_refuses_leakage() -> None:
    result = import_fixture(context=_context(), fixture_name="bitcoin_block.json", now=NOW)
    assert result.observation is not None
    with pytest.raises(FeatureLeakageError):
        compute_btc_fee_regime(
            observation=result.observation,
            as_of=NOW - timedelta(seconds=1),
        )


def test_feature_and_signal_happy_path() -> None:
    result = import_fixture(context=_context(), fixture_name="bitcoin_block.json", now=NOW)
    assert result.observation is not None
    feature = compute_btc_fee_regime(observation=result.observation, as_of=NOW)
    assert feature.value == "12.5"
    signal = detect_fee_regime_signal(
        observation=result.observation,
        feature=feature,
        detected_at=NOW,
    )
    assert signal is not None
    assert signal.can_place_trade is False


def test_reorg_marks_orphaned_preserving_id() -> None:
    result = import_fixture(context=_context(), fixture_name="bitcoin_block.json", now=NOW)
    assert result.observation is not None
    orphaned = mark_orphaned(result.observation)
    assert orphaned.header.observation_id == result.observation.header.observation_id
    assert orphaned.header.quality is ObservationQuality.ORPHANED
    assert orphaned.header.finality is FinalityState.ORPHANED


def test_analytics_backends_blocked() -> None:
    gates = analytics_gates()
    assert any(gate.backend is AnalyticsBackend.DUCKDB for gate in gates)
    with pytest.raises(AnalyticsBackendBlocked):
        require_postgres_only(AnalyticsBackend.PARQUET)


def test_quality_quarantine_type() -> None:
    with pytest.raises(QualityQuarantine):
        raise QualityQuarantine(("sequence_gap",))
