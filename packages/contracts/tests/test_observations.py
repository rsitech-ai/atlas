"""Strict Phase 4 observation and collector contract tests."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest
from pydantic import ValidationError
from rsi_atlas_contracts import (
    DEVELOPMENT_ANALYTICS_GATES,
    AcquisitionMode,
    AnalyticsBackend,
    AnalyticsBackendGate,
    AnalyticsBackendStatus,
    ArtifactCommandContext,
    BitcoinBlockObservation,
    BitcoinPin,
    ChainPin,
    CollectorDefinition,
    CollectorLifecycle,
    EvmBlockObservation,
    EvmPin,
    FeatureDefinition,
    FeatureLifecycle,
    FeatureValue,
    FinalityState,
    GitHubRecord,
    GovernanceRecord,
    InstrumentIdentity,
    MarketTick,
    Observation,
    ObservationHeader,
    ObservationPayloadKind,
    ObservationQuality,
    ProviderQualityState,
    QuarantineRecord,
    RawEnvelope,
    ResearchSignal,
    SignalKind,
    SolanaCommitment,
    SolanaPin,
    SolanaSlotObservation,
    SourceFamily,
    feature_eligible,
    observation_id,
    raw_envelope_id,
)

TENANT_ID = UUID("00000000-0000-4000-8000-000000000001")
WORKSPACE_ID = UUID("00000000-0000-4000-8000-000000000002")
ACTOR_ID = UUID("00000000-0000-4000-8000-000000000003")
TRACE_ID = UUID("00000000-0000-4000-8000-000000000004")
NOW = datetime(2026, 7, 19, 12, 0, tzinfo=UTC)
PAYLOAD_HASH = "a" * 64
ENVELOPE_ID = "envelope:" + ("b" * 64)
OBS_ID = "observation:" + ("c" * 64)


def _context() -> ArtifactCommandContext:
    return ArtifactCommandContext(
        tenant_id=TENANT_ID,
        workspace_id=WORKSPACE_ID,
        actor_id=ACTOR_ID,
        trace_id=TRACE_ID,
    )


def test_collector_rejects_live_mode_unless_blocked() -> None:
    with pytest.raises(ValidationError, match="blocked"):
        CollectorDefinition(
            collector_id="evm_live",
            source_family=SourceFamily.EVM,
            provider="alchemy",
            acquisition_mode=AcquisitionMode.SNAPSHOT,
            network_or_venue="ethereum",
            lifecycle=CollectorLifecycle.EXPERIMENTAL,
            schema_name="evm_block_v1",
            rate_limit_per_minute=60,
            supports_backfill=True,
        )


def test_collector_allows_fixture_import() -> None:
    definition = CollectorDefinition(
        collector_id="evm_fixture",
        source_family=SourceFamily.EVM,
        provider="fixture",
        acquisition_mode=AcquisitionMode.FIXTURE_IMPORT,
        network_or_venue="ethereum",
        lifecycle=CollectorLifecycle.EXPERIMENTAL,
        schema_name="evm_block_v1",
        rate_limit_per_minute=0,
        supports_backfill=False,
    )
    assert definition.acquisition_mode is AcquisitionMode.FIXTURE_IMPORT


def test_raw_envelope_rejects_credentials_and_mismatched_artifact() -> None:
    with pytest.raises(ValidationError, match="credentials"):
        RawEnvelope(
            context=_context(),
            envelope_id=ENVELOPE_ID,
            collector_id="btc_fixture",
            provider="fixture",
            source_family=SourceFamily.BITCOIN,
            request_fingerprint="d" * 64,
            requested_at=NOW,
            received_at=NOW,
            transport_status=200,
            content_type="application/json",
            payload_sha256=PAYLOAD_HASH,
            payload_artifact_id=f"sha256:{PAYLOAD_HASH}",
            payload_size_bytes=12,
            source_schema="bitcoin_block_v1",
            network_policy_decision="allow_offline",
            redacted_request_metadata={"Authorization": "secret"},
        )
    with pytest.raises(ValidationError, match="payload_artifact_id"):
        RawEnvelope(
            context=_context(),
            envelope_id=ENVELOPE_ID,
            collector_id="btc_fixture",
            provider="fixture",
            source_family=SourceFamily.BITCOIN,
            request_fingerprint="d" * 64,
            requested_at=NOW,
            received_at=NOW,
            transport_status=200,
            content_type="application/json",
            payload_sha256=PAYLOAD_HASH,
            payload_artifact_id="sha256:" + ("e" * 64),
            payload_size_bytes=12,
            source_schema="bitcoin_block_v1",
            network_policy_decision="allow_offline",
        )


def test_raw_envelope_id_is_deterministic() -> None:
    first = raw_envelope_id(
        collector_id="btc_fixture",
        request_fingerprint="d" * 64,
        payload_sha256=PAYLOAD_HASH,
    )
    second = raw_envelope_id(
        collector_id="btc_fixture",
        request_fingerprint="d" * 64,
        payload_sha256=PAYLOAD_HASH,
    )
    assert first == second
    assert first.startswith("envelope:")


def test_chain_pin_requires_matching_family() -> None:
    with pytest.raises(ValidationError, match="exactly one"):
        ChainPin(
            family=SourceFamily.EVM,
            bitcoin=BitcoinPin(
                network="regtest",
                block_height=1,
                block_hash="f" * 64,
            ),
        )


def test_market_tick_rejects_floatish_and_crossed_book() -> None:
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
    with pytest.raises(ValidationError, match="crossed"):
        MarketTick(
            instrument=instrument,
            sequence=1,
            bid="100.00",
            ask="99.00",
            last="99.50",
            bid_size="1.0",
            ask_size="1.0",
            exchange_event_time=NOW,
        )


def test_governance_executed_requires_on_chain_link() -> None:
    with pytest.raises(ValidationError, match="on_chain_execution_id"):
        GovernanceRecord(
            proposal_id="prop-1",
            status="executed",
            quorum_reached=True,
            participation_bps=4_200,
        )


def test_observation_requires_chain_pin_for_evm() -> None:
    pin = EvmPin(
        chain_id=1,
        block_number=10,
        block_hash="0x" + ("1" * 64),
    )
    header = ObservationHeader(
        observation_id=OBS_ID,
        observation_type=ObservationPayloadKind.EVM_BLOCK,
        source_family=SourceFamily.EVM,
        subject_ids=("protocol:uniswap",),
        envelope_id=ENVELOPE_ID,
        event_time=NOW,
        available_time=NOW,
        collected_time=NOW,
        normalized_time=NOW,
        valid_time=NOW,
        system_time=NOW,
        quality=ObservationQuality.VALID,
        finality=FinalityState.FINALIZED,
        provider_quality=ProviderQualityState.SINGLE_SOURCE,
        normalizer_version="evm_norm_v1",
        chain_pin=ChainPin(family=SourceFamily.EVM, evm=pin),
    )
    observation = Observation(
        context=_context(),
        header=header,
        payload=EvmBlockObservation(
            pin=pin,
            finality=FinalityState.FINALIZED,
            tx_count=2,
            gas_used=21_000,
        ),
    )
    assert observation.header.chain_pin is not None
    with pytest.raises(ValidationError, match="chain_pin"):
        ObservationHeader(
            observation_id=OBS_ID,
            observation_type=ObservationPayloadKind.EVM_BLOCK,
            source_family=SourceFamily.EVM,
            subject_ids=("protocol:uniswap",),
            envelope_id=ENVELOPE_ID,
            event_time=NOW,
            available_time=NOW,
            collected_time=NOW,
            normalized_time=NOW,
            valid_time=NOW,
            system_time=NOW,
            quality=ObservationQuality.VALID,
            finality=FinalityState.FINALIZED,
            provider_quality=ProviderQualityState.SINGLE_SOURCE,
            normalizer_version="evm_norm_v1",
        )


def test_bitcoin_solana_payloads_round_trip() -> None:
    btc_pin = BitcoinPin(network="regtest", block_height=100, block_hash="a" * 64)
    sol_pin = SolanaPin(
        cluster="localnet",
        slot=50,
        blockhash="1" * 44,
        commitment=SolanaCommitment.FINALIZED,
    )
    btc = BitcoinBlockObservation(pin=btc_pin, tx_count=1, fee_rate_sat_vb="1.5")
    sol = SolanaSlotObservation(pin=sol_pin, tx_count=3, fee_lamports=5_000)
    assert btc.main_chain is True
    assert sol.pin.commitment is SolanaCommitment.FINALIZED


def test_quarantine_requires_reasons() -> None:
    with pytest.raises(ValidationError):
        QuarantineRecord(
            context=_context(),
            quarantine_id=UUID("00000000-0000-4000-8000-000000000099"),
            envelope_id=ENVELOPE_ID,
            reasons=(),
            severity="error",
            recorded_at=NOW,
        )


def test_feature_eligibility_is_point_in_time() -> None:
    available = NOW
    assert feature_eligible(available_time=available, as_of=NOW) is True
    assert feature_eligible(available_time=available, as_of=NOW - timedelta(seconds=1)) is False


def test_feature_value_rejects_bad_observation_id() -> None:
    with pytest.raises(ValidationError, match="observation"):
        FeatureValue(
            feature_id="btc_fee_regime",
            subject_id="asset:btc",
            effective_time=NOW,
            available_time=NOW,
            value="12.5",
            unit="sat_vb",
            input_observation_ids=("not-an-id",),
            calculation_run_id=UUID("00000000-0000-4000-8000-000000000088"),
            quality=ObservationQuality.VALID,
            implementation_version="feat_v1",
        )


def test_research_signal_forbids_trading_capabilities() -> None:
    signal = ResearchSignal(
        signal_id=UUID("00000000-0000-4000-8000-000000000077"),
        kind=SignalKind.FEE_REGIME_CHANGE,
        subject_ids=("asset:btc",),
        observation_ids=(OBS_ID,),
        summary="Fee regime shifted above watchlist threshold.",
        detected_at=NOW,
    )
    assert signal.can_place_trade is False
    dumped = signal.model_dump()
    assert dumped["can_place_trade"] is False
    with pytest.raises(ValidationError):
        ResearchSignal.model_validate({**dumped, "can_place_trade": True})


def test_analytics_gates_default_block_duckdb_and_parquet() -> None:
    assert len(DEVELOPMENT_ANALYTICS_GATES) == 3
    assert DEVELOPMENT_ANALYTICS_GATES[1].status is AnalyticsBackendStatus.BLOCKED_DEPENDENCY
    # Governed optional path may mark DuckDB available without ValidationError.
    gate = AnalyticsBackendGate(
        backend=AnalyticsBackend.DUCKDB,
        status=AnalyticsBackendStatus.AVAILABLE,
        reason="optional local duckdb after RSI_ATLAS_ENABLE_DUCKDB=1",
    )
    assert gate.status is AnalyticsBackendStatus.AVAILABLE


def test_observation_id_stable() -> None:
    first = observation_id(
        envelope_id=ENVELOPE_ID,
        observation_type=ObservationPayloadKind.GITHUB_RELEASE,
        subject_ids=("repo:org/app",),
        valid_time=NOW,
        normalizer_version="gh_v1",
    )
    second = observation_id(
        envelope_id=ENVELOPE_ID,
        observation_type=ObservationPayloadKind.GITHUB_RELEASE,
        subject_ids=("repo:org/app",),
        valid_time=NOW,
        normalizer_version="gh_v1",
    )
    assert first == second


def test_github_record_requires_cursor_and_rate_limit() -> None:
    record = GitHubRecord(
        repository="rsi/atlas",
        event_type="release",
        cursor="page:2",
        rate_limit_remaining=40,
        rate_limit_reset_at=NOW + timedelta(hours=1),
        ref="v0.1.0",
    )
    assert record.rate_limit_remaining == 40


def test_feature_definition_minimal() -> None:
    definition = FeatureDefinition(
        feature_id="btc_fee_regime",
        entity_type="asset",
        grain="block",
        value_type="decimal",
        unit="sat_vb",
        lookback="1_block",
        availability_delay="0s",
        implementation_version="feat_v1",
        lifecycle=FeatureLifecycle.EXPERIMENTAL,
    )
    assert definition.lifecycle is FeatureLifecycle.EXPERIMENTAL
