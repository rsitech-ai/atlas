"""Strict structured-data contracts for Phase 4 (sections 19-23 development slice)."""

from __future__ import annotations

import re
from datetime import datetime, timedelta
from decimal import Decimal
from enum import StrEnum
from hashlib import sha256
from json import dumps
from typing import Literal, Self
from uuid import UUID

from pydantic import Field, StrictBool, StrictInt, field_validator, model_validator

from rsi_atlas_contracts.artifact import ArtifactCommandContext
from rsi_atlas_contracts.document_parsing import DocumentContractModel

_SHA256_PATTERN = r"^[0-9a-f]{64}$"
_ENVELOPE_ID_PATTERN = r"^envelope:[0-9a-f]{64}$"
_OBSERVATION_ID_PATTERN = r"^observation:[0-9a-f]{64}$"
_COLLECTOR_ID_PATTERN = r"^[a-z][a-z0-9_]{0,63}$"
_SUBJECT_PATTERN = r"^[a-z0-9][a-z0-9:_./-]{0,127}$"
_PROVIDER_PATTERN = r"^[a-z][a-z0-9_-]{0,63}$"
_FIXED_DECIMAL_PATTERN = r"^-?(?:0|[1-9][0-9]{0,38})(?:\.[0-9]{1,18})?$"


def _require_utc(value: datetime, *, field_name: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() != timedelta(0):
        raise ValueError(f"{field_name} must be timezone-aware UTC")
    return value


def _canonical_json(payload: object) -> str:
    return dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


class SourceFamily(StrEnum):
    BITCOIN = "bitcoin"
    EVM = "evm"
    SOLANA = "solana"
    MARKET = "market"
    PROTOCOL = "protocol"
    GOVERNANCE = "governance"
    GITHUB = "github"


class AcquisitionMode(StrEnum):
    SNAPSHOT = "snapshot"
    INCREMENTAL_POLL = "incremental_poll"
    WEBSOCKET_STREAM = "websocket_stream"
    LOCAL_NODE_SUBSCRIPTION = "local_node_subscription"
    FILESYSTEM_IMPORT = "filesystem_import"
    BUNDLE_IMPORT = "bundle_import"
    ON_DEMAND = "on_demand"
    FIXTURE_IMPORT = "fixture_import"


# Development slice: only offline/fixture acquisition is permitted.
DEVELOPMENT_ACQUISITION_MODES = frozenset(
    {
        AcquisitionMode.FIXTURE_IMPORT,
        AcquisitionMode.FILESYSTEM_IMPORT,
        AcquisitionMode.BUNDLE_IMPORT,
    }
)

LIVE_ACQUISITION_MODES = frozenset(
    {
        AcquisitionMode.SNAPSHOT,
        AcquisitionMode.INCREMENTAL_POLL,
        AcquisitionMode.WEBSOCKET_STREAM,
        AcquisitionMode.LOCAL_NODE_SUBSCRIPTION,
        AcquisitionMode.ON_DEMAND,
    }
)


class CollectorLifecycle(StrEnum):
    EXPERIMENTAL = "experimental"
    CANDIDATE = "candidate"
    PRODUCTION = "production"
    DEPRECATED = "deprecated"
    RETIRED = "retired"
    BLOCKED = "blocked"


class FinalityState(StrEnum):
    OBSERVED = "observed"
    PROVISIONAL = "provisional"
    SAFE = "safe"
    FINALIZED = "finalized"
    ORPHANED = "orphaned"


class SolanaCommitment(StrEnum):
    PROCESSED = "processed"
    CONFIRMED = "confirmed"
    FINALIZED = "finalized"
    INVALIDATED = "invalidated"


class ProviderQualityState(StrEnum):
    SINGLE_SOURCE = "single_source"
    CROSS_VERIFIED = "cross_verified"
    DEGRADED = "degraded"
    CONFLICTED = "conflicted"
    UNAVAILABLE = "unavailable"
    INVALID = "invalid"


class ObservationQuality(StrEnum):
    VALID = "valid"
    QUARANTINED = "quarantined"
    CONFLICTED = "conflicted"
    ORPHANED = "orphaned"
    STALE = "stale"


class ObservationPayloadKind(StrEnum):
    BITCOIN_BLOCK = "bitcoin_block"
    EVM_BLOCK = "evm_block"
    SOLANA_SLOT = "solana_slot"
    MARKET_TICK = "market_tick"
    GOVERNANCE_PROPOSAL = "governance_proposal"
    GITHUB_RELEASE = "github_release"


class FeatureLifecycle(StrEnum):
    EXPERIMENTAL = "experimental"
    CANDIDATE = "candidate"
    PRODUCTION = "production"
    DEPRECATED = "deprecated"
    RETIRED = "retired"


class AnalyticsBackend(StrEnum):
    POSTGRES = "postgres"
    DUCKDB = "duckdb"
    PARQUET = "parquet"


class AnalyticsBackendStatus(StrEnum):
    AVAILABLE = "available"
    BLOCKED_DEPENDENCY = "blocked_dependency"


class SignalKind(StrEnum):
    LIQUIDITY_DETERIORATION = "liquidity_deterioration"
    GOVERNANCE_CONCENTRATION = "governance_concentration"
    UPGRADE_DETECTION = "upgrade_detection"
    DEVELOPMENT_DECLINE = "development_decline"
    MARKET_ONCHAIN_DIVERGENCE = "market_onchain_divergence"
    FEE_REGIME_CHANGE = "fee_regime_change"


class EvmPin(DocumentContractModel):
    chain_id: StrictInt = Field(ge=1)
    block_number: StrictInt = Field(ge=0)
    block_hash: str = Field(pattern=r"^0x[0-9a-f]{64}$")


class SolanaPin(DocumentContractModel):
    cluster: str = Field(pattern=r"^[a-z][a-z0-9_-]{0,31}$")
    slot: StrictInt = Field(ge=0)
    blockhash: str = Field(min_length=32, max_length=88)
    commitment: SolanaCommitment


class BitcoinPin(DocumentContractModel):
    network: str = Field(pattern=r"^(mainnet|testnet|regtest|signet)$")
    block_height: StrictInt = Field(ge=0)
    block_hash: str = Field(pattern=r"^[0-9a-f]{64}$")


class ChainPin(DocumentContractModel):
    family: Literal[SourceFamily.BITCOIN, SourceFamily.EVM, SourceFamily.SOLANA]
    bitcoin: BitcoinPin | None = None
    evm: EvmPin | None = None
    solana: SolanaPin | None = None

    @model_validator(mode="after")
    def exactly_one_pin(self) -> Self:
        pins = {
            SourceFamily.BITCOIN: self.bitcoin,
            SourceFamily.EVM: self.evm,
            SourceFamily.SOLANA: self.solana,
        }
        present = {family for family, pin in pins.items() if pin is not None}
        if present != {self.family}:
            raise ValueError("chain pin family must match exactly one populated pin")
        return self


class CollectorDefinition(DocumentContractModel):
    schema_version: Literal["1.0.0"] = "1.0.0"
    collector_id: str = Field(pattern=_COLLECTOR_ID_PATTERN)
    source_family: SourceFamily
    provider: str = Field(pattern=_PROVIDER_PATTERN)
    acquisition_mode: AcquisitionMode
    network_or_venue: str = Field(min_length=1, max_length=128)
    lifecycle: CollectorLifecycle
    schema_name: str = Field(min_length=1, max_length=64)
    rate_limit_per_minute: StrictInt = Field(ge=0, le=100_000)
    supports_backfill: StrictBool
    allowlist: tuple[str, ...] = Field(default=(), max_length=32)

    @model_validator(mode="after")
    def live_modes_require_allowlist_or_blocked(self) -> Self:
        if self.acquisition_mode not in LIVE_ACQUISITION_MODES:
            return self
        if self.lifecycle is CollectorLifecycle.BLOCKED:
            return self
        if self.allowlist:
            return self
        raise ValueError(
            "live acquisition modes require a non-empty allowlist or lifecycle=blocked; "
            "default remains fixture_import/filesystem_import/bundle_import"
        )


class RawEnvelope(DocumentContractModel):
    schema_version: Literal["1.0.0"] = "1.0.0"
    context: ArtifactCommandContext
    envelope_id: str = Field(pattern=_ENVELOPE_ID_PATTERN)
    collector_id: str = Field(pattern=_COLLECTOR_ID_PATTERN)
    provider: str = Field(pattern=_PROVIDER_PATTERN)
    source_family: SourceFamily
    request_fingerprint: str = Field(pattern=_SHA256_PATTERN)
    requested_at: datetime
    received_at: datetime
    event_time_hint: datetime | None = None
    cursor_before: str | None = Field(default=None, max_length=256)
    cursor_after: str | None = Field(default=None, max_length=256)
    transport_status: StrictInt = Field(ge=0, le=599)
    content_type: str = Field(min_length=1, max_length=128)
    payload_sha256: str = Field(pattern=_SHA256_PATTERN)
    payload_artifact_id: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    payload_size_bytes: StrictInt = Field(ge=0, le=64 * 1024 * 1024)
    source_schema: str = Field(min_length=1, max_length=64)
    network_policy_decision: Literal["allow_offline", "deny_live", "allow_monitored"]
    redacted_request_metadata: dict[str, str] = Field(default_factory=dict)

    @field_validator("requested_at", "received_at", "event_time_hint")
    @classmethod
    def utc_times(cls, value: datetime | None, info: object) -> datetime | None:
        if value is None:
            return None
        field_name = getattr(info, "field_name", "timestamp")
        return _require_utc(value, field_name=str(field_name))

    @model_validator(mode="after")
    def payload_artifact_matches_hash(self) -> Self:
        if self.payload_artifact_id != f"sha256:{self.payload_sha256}":
            raise ValueError("payload_artifact_id must match payload_sha256")
        if self.received_at < self.requested_at:
            raise ValueError("received_at must be >= requested_at")
        if "authorization" in {key.lower() for key in self.redacted_request_metadata}:
            raise ValueError("credentials must not appear in redacted_request_metadata")
        return self


def raw_envelope_id(
    *,
    collector_id: str,
    request_fingerprint: str,
    payload_sha256: str,
) -> str:
    payload = {
        "collector_id": collector_id,
        "payload_sha256": payload_sha256,
        "request_fingerprint": request_fingerprint,
    }
    return f"envelope:{sha256(_canonical_json(payload).encode()).hexdigest()}"


class InstrumentIdentity(DocumentContractModel):
    venue: str = Field(min_length=1, max_length=64)
    venue_symbol: str = Field(min_length=1, max_length=64)
    base: str = Field(min_length=1, max_length=32)
    quote: str = Field(min_length=1, max_length=32)
    instrument_type: Literal[
        "spot", "perpetual", "future", "option", "dex_pool", "wrapped", "synthetic"
    ]
    tick_size: str = Field(pattern=_FIXED_DECIMAL_PATTERN)
    quantity_step: str = Field(pattern=_FIXED_DECIMAL_PATTERN)
    multiplier: str = Field(pattern=_FIXED_DECIMAL_PATTERN)
    status: Literal["active", "halted", "delisted"] = "active"

    @model_validator(mode="after")
    def positive_precision_fields(self) -> Self:
        for name in ("tick_size", "quantity_step", "multiplier"):
            value = Decimal(getattr(self, name))
            if value <= 0:
                raise ValueError(f"{name} must be positive exact decimal")
        return self


class MarketTick(DocumentContractModel):
    instrument: InstrumentIdentity
    sequence: StrictInt = Field(ge=0)
    trade_id: str | None = Field(default=None, max_length=128)
    bid: str = Field(pattern=_FIXED_DECIMAL_PATTERN)
    ask: str = Field(pattern=_FIXED_DECIMAL_PATTERN)
    last: str = Field(pattern=_FIXED_DECIMAL_PATTERN)
    bid_size: str = Field(pattern=_FIXED_DECIMAL_PATTERN)
    ask_size: str = Field(pattern=_FIXED_DECIMAL_PATTERN)
    exchange_event_time: datetime

    @field_validator("exchange_event_time")
    @classmethod
    def utc_event(cls, value: datetime) -> datetime:
        return _require_utc(value, field_name="exchange_event_time")

    @model_validator(mode="after")
    def book_not_crossed(self) -> Self:
        bid = Decimal(self.bid)
        ask = Decimal(self.ask)
        if bid <= 0 or ask <= 0 or Decimal(self.last) <= 0:
            raise ValueError("prices must be positive exact decimals")
        if bid >= ask:
            raise ValueError("order book must not be crossed")
        return self


class BitcoinBlockObservation(DocumentContractModel):
    pin: BitcoinPin
    tx_count: StrictInt = Field(ge=0)
    fee_rate_sat_vb: str = Field(pattern=_FIXED_DECIMAL_PATTERN)
    main_chain: StrictBool = True


class EvmBlockObservation(DocumentContractModel):
    pin: EvmPin
    finality: FinalityState
    tx_count: StrictInt = Field(ge=0)
    gas_used: StrictInt = Field(ge=0)


class SolanaSlotObservation(DocumentContractModel):
    pin: SolanaPin
    tx_count: StrictInt = Field(ge=0)
    fee_lamports: StrictInt = Field(ge=0)


class GovernanceRecord(DocumentContractModel):
    proposal_id: str = Field(min_length=1, max_length=128)
    on_chain_execution_id: str | None = Field(default=None, max_length=128)
    off_chain_discussion_id: str | None = Field(default=None, max_length=128)
    status: Literal["draft", "active", "passed", "failed", "executed", "cancelled", "vetoed"]
    quorum_reached: StrictBool
    participation_bps: StrictInt = Field(ge=0, le=10_000)

    @model_validator(mode="after")
    def link_identities_when_executed(self) -> Self:
        if self.status == "executed" and self.on_chain_execution_id is None:
            raise ValueError("executed governance requires on_chain_execution_id")
        return self


class GitHubRecord(DocumentContractModel):
    repository: str = Field(pattern=r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
    event_type: Literal["commit", "tag", "release", "pull_request", "issue", "advisory", "workflow"]
    cursor: str = Field(min_length=1, max_length=256)
    rate_limit_remaining: StrictInt = Field(ge=0, le=100_000)
    rate_limit_reset_at: datetime
    ref: str = Field(min_length=1, max_length=256)
    is_bot: StrictBool = False

    @field_validator("rate_limit_reset_at")
    @classmethod
    def utc_reset(cls, value: datetime) -> datetime:
        return _require_utc(value, field_name="rate_limit_reset_at")


class ObservationHeader(DocumentContractModel):
    observation_id: str = Field(pattern=_OBSERVATION_ID_PATTERN)
    observation_type: ObservationPayloadKind
    source_family: SourceFamily
    subject_ids: tuple[str, ...] = Field(min_length=1, max_length=32)
    envelope_id: str = Field(pattern=_ENVELOPE_ID_PATTERN)
    event_time: datetime
    available_time: datetime
    collected_time: datetime
    normalized_time: datetime
    valid_time: datetime
    system_time: datetime
    quality: ObservationQuality
    finality: FinalityState | SolanaCommitment | None = None
    provider_quality: ProviderQualityState
    normalizer_version: str = Field(pattern=r"^[a-z0-9][a-z0-9._-]{0,63}$")
    schema_version: Literal["1.0.0"] = "1.0.0"
    chain_pin: ChainPin | None = None

    @field_validator(
        "event_time",
        "available_time",
        "collected_time",
        "normalized_time",
        "valid_time",
        "system_time",
    )
    @classmethod
    def utc_header_times(cls, value: datetime, info: object) -> datetime:
        field_name = getattr(info, "field_name", "timestamp")
        return _require_utc(value, field_name=str(field_name))

    @field_validator("subject_ids")
    @classmethod
    def validate_subjects(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        for subject in value:
            if not re.fullmatch(_SUBJECT_PATTERN, subject):
                raise ValueError(f"invalid subject_id: {subject}")
        return value

    @model_validator(mode="after")
    def chain_families_require_pin(self) -> Self:
        if self.source_family in {
            SourceFamily.BITCOIN,
            SourceFamily.EVM,
            SourceFamily.SOLANA,
        }:
            if self.chain_pin is None or self.chain_pin.family != self.source_family:
                raise ValueError("chain observations require a matching chain_pin")
        elif self.chain_pin is not None:
            raise ValueError("non-chain observations must not carry chain_pin")
        if self.available_time < self.event_time:
            raise ValueError("available_time must be >= event_time")
        return self


class Observation(DocumentContractModel):
    schema_version: Literal["1.0.0"] = "1.0.0"
    context: ArtifactCommandContext
    header: ObservationHeader
    payload: (
        BitcoinBlockObservation
        | EvmBlockObservation
        | SolanaSlotObservation
        | MarketTick
        | GovernanceRecord
        | GitHubRecord
    )

    @model_validator(mode="after")
    def payload_matches_type(self) -> Self:
        kind = self.header.observation_type
        payload = self.payload
        expected: dict[ObservationPayloadKind, type] = {
            ObservationPayloadKind.BITCOIN_BLOCK: BitcoinBlockObservation,
            ObservationPayloadKind.EVM_BLOCK: EvmBlockObservation,
            ObservationPayloadKind.SOLANA_SLOT: SolanaSlotObservation,
            ObservationPayloadKind.MARKET_TICK: MarketTick,
            ObservationPayloadKind.GOVERNANCE_PROPOSAL: GovernanceRecord,
            ObservationPayloadKind.GITHUB_RELEASE: GitHubRecord,
        }
        if not isinstance(payload, expected[kind]):
            raise ValueError("payload type must match observation_type")
        return self


def observation_id(
    *,
    envelope_id: str,
    observation_type: ObservationPayloadKind,
    subject_ids: tuple[str, ...],
    valid_time: datetime,
    normalizer_version: str,
) -> str:
    payload = {
        "envelope_id": envelope_id,
        "normalizer_version": normalizer_version,
        "observation_type": observation_type.value,
        "subject_ids": list(subject_ids),
        "valid_time": valid_time.isoformat().replace("+00:00", "Z"),
    }
    return f"observation:{sha256(_canonical_json(payload).encode()).hexdigest()}"


class QuarantineRecord(DocumentContractModel):
    schema_version: Literal["1.0.0"] = "1.0.0"
    context: ArtifactCommandContext
    quarantine_id: UUID
    envelope_id: str = Field(pattern=_ENVELOPE_ID_PATTERN)
    observation_id: str | None = Field(default=None, pattern=_OBSERVATION_ID_PATTERN)
    reasons: tuple[str, ...] = Field(min_length=1, max_length=16)
    severity: Literal["warning", "error", "critical"]
    recorded_at: datetime

    @field_validator("recorded_at")
    @classmethod
    def utc_recorded(cls, value: datetime) -> datetime:
        return _require_utc(value, field_name="recorded_at")

    @field_validator("reasons")
    @classmethod
    def nonempty_reasons(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        for reason in value:
            if not reason.strip():
                raise ValueError("quarantine reasons must be non-empty")
        return value


class FeatureDefinition(DocumentContractModel):
    schema_version: Literal["1.0.0"] = "1.0.0"
    feature_id: str = Field(pattern=r"^[a-z][a-z0-9_]{0,63}$")
    entity_type: str = Field(min_length=1, max_length=64)
    grain: str = Field(min_length=1, max_length=64)
    value_type: Literal["decimal", "integer", "boolean", "ratio"]
    unit: str = Field(min_length=1, max_length=32)
    lookback: str = Field(min_length=1, max_length=32)
    availability_delay: str = Field(min_length=1, max_length=32)
    implementation_version: str = Field(pattern=r"^[a-z0-9][a-z0-9._-]{0,63}$")
    lifecycle: FeatureLifecycle
    dependencies: tuple[str, ...] = Field(default=(), max_length=32)


class FeatureValue(DocumentContractModel):
    schema_version: Literal["1.0.0"] = "1.0.0"
    feature_id: str = Field(pattern=r"^[a-z][a-z0-9_]{0,63}$")
    subject_id: str = Field(pattern=_SUBJECT_PATTERN)
    effective_time: datetime
    available_time: datetime
    value: str = Field(pattern=_FIXED_DECIMAL_PATTERN)
    unit: str = Field(min_length=1, max_length=32)
    input_observation_ids: tuple[str, ...] = Field(min_length=1, max_length=64)
    calculation_run_id: UUID
    quality: ObservationQuality
    implementation_version: str = Field(pattern=r"^[a-z0-9][a-z0-9._-]{0,63}$")

    @field_validator("effective_time", "available_time")
    @classmethod
    def utc_feature_times(cls, value: datetime, info: object) -> datetime:
        field_name = getattr(info, "field_name", "timestamp")
        return _require_utc(value, field_name=str(field_name))

    @model_validator(mode="after")
    def available_after_effective(self) -> Self:
        if self.available_time < self.effective_time:
            raise ValueError("available_time must be >= effective_time")
        for obs_id in self.input_observation_ids:
            if not re.fullmatch(_OBSERVATION_ID_PATTERN, obs_id):
                raise ValueError(f"invalid observation id: {obs_id}")
        return self


def feature_eligible(*, available_time: datetime, as_of: datetime) -> bool:
    available_time = _require_utc(available_time, field_name="available_time")
    as_of = _require_utc(as_of, field_name="as_of")
    return available_time <= as_of


class ResearchSignal(DocumentContractModel):
    schema_version: Literal["1.0.0"] = "1.0.0"
    signal_id: UUID
    kind: SignalKind
    subject_ids: tuple[str, ...] = Field(min_length=1, max_length=32)
    observation_ids: tuple[str, ...] = Field(min_length=1, max_length=64)
    feature_ids: tuple[str, ...] = Field(default=(), max_length=32)
    summary: str = Field(min_length=1, max_length=512)
    detected_at: datetime
    # Explicit non-capability fields — trading/signing must never appear.
    can_place_trade: Literal[False] = False
    can_sign_transaction: Literal[False] = False
    can_access_exchange_account: Literal[False] = False

    @field_validator("detected_at")
    @classmethod
    def utc_detected(cls, value: datetime) -> datetime:
        return _require_utc(value, field_name="detected_at")

    @model_validator(mode="after")
    def non_trading_only(self) -> Self:
        if self.can_place_trade or self.can_sign_transaction or self.can_access_exchange_account:
            raise ValueError("research signals cannot trade, sign, or access exchanges")
        return self


class AnalyticsBackendGate(DocumentContractModel):
    backend: AnalyticsBackend
    status: AnalyticsBackendStatus
    reason: str = Field(min_length=1, max_length=256)

    @model_validator(mode="after")
    def postgres_available(self) -> Self:
        if (
            self.backend == AnalyticsBackend.POSTGRES
            and self.status != AnalyticsBackendStatus.AVAILABLE
        ):
            raise ValueError("postgres analytics backend must be available in-slice")
        return self


# Default gates stay blocked for DuckDB/Parquet until RSI_ATLAS_ENABLE_DUCKDB=1 at runtime.
DEVELOPMENT_ANALYTICS_GATES = (
    AnalyticsBackendGate(
        backend=AnalyticsBackend.POSTGRES,
        status=AnalyticsBackendStatus.AVAILABLE,
        reason="postgresql stores operational normalized observations",
    ),
    AnalyticsBackendGate(
        backend=AnalyticsBackend.DUCKDB,
        status=AnalyticsBackendStatus.BLOCKED_DEPENDENCY,
        reason="duckdb optional; enable with RSI_ATLAS_ENABLE_DUCKDB=1 after install",
    ),
    AnalyticsBackendGate(
        backend=AnalyticsBackend.PARQUET,
        status=AnalyticsBackendStatus.BLOCKED_DEPENDENCY,
        reason="parquet via duckdb optional path",
    ),
)
