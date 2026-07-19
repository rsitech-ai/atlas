"""Normalize offline fixture JSON into typed observation payloads."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from rsi_atlas_contracts import (
    BitcoinBlockObservation,
    BitcoinPin,
    ChainPin,
    EvmBlockObservation,
    EvmPin,
    FinalityState,
    GitHubRecord,
    GovernanceRecord,
    InstrumentIdentity,
    MarketTick,
    ObservationPayloadKind,
    SolanaCommitment,
    SolanaPin,
    SolanaSlotObservation,
    SourceFamily,
)

from rsi_atlas_collectors.errors import FixtureNormalizationError

_NORMALIZER_VERSION = "fixture_norm_v1"


def normalizer_version() -> str:
    return _NORMALIZER_VERSION


def parse_source_family(raw: dict[str, Any]) -> SourceFamily:
    try:
        return SourceFamily(str(raw["family"]))
    except (KeyError, ValueError) as error:
        raise FixtureNormalizationError("fixture missing valid family") from error


def payload_kind_for(family: SourceFamily) -> ObservationPayloadKind:
    mapping = {
        SourceFamily.BITCOIN: ObservationPayloadKind.BITCOIN_BLOCK,
        SourceFamily.EVM: ObservationPayloadKind.EVM_BLOCK,
        SourceFamily.SOLANA: ObservationPayloadKind.SOLANA_SLOT,
        SourceFamily.MARKET: ObservationPayloadKind.MARKET_TICK,
        SourceFamily.GOVERNANCE: ObservationPayloadKind.GOVERNANCE_PROPOSAL,
        SourceFamily.GITHUB: ObservationPayloadKind.GITHUB_RELEASE,
    }
    try:
        return mapping[family]
    except KeyError as error:
        raise FixtureNormalizationError(f"unsupported fixture family: {family}") from error


def normalize_payload(
    raw: dict[str, Any],
) -> tuple[
    SourceFamily,
    ObservationPayloadKind,
    BitcoinBlockObservation
    | EvmBlockObservation
    | SolanaSlotObservation
    | MarketTick
    | GovernanceRecord
    | GitHubRecord,
    ChainPin | None,
    tuple[str, ...],
]:
    family = parse_source_family(raw)
    kind = payload_kind_for(family)
    subjects = tuple(str(item) for item in raw.get("subject_ids", ()))
    if not subjects:
        raise FixtureNormalizationError("fixture requires subject_ids")

    if family is SourceFamily.BITCOIN:
        bitcoin_pin = BitcoinPin(
            network=str(raw["network"]),
            block_height=int(raw["block_height"]),
            block_hash=str(raw["block_hash"]),
        )
        bitcoin_payload = BitcoinBlockObservation(
            pin=bitcoin_pin,
            tx_count=int(raw["tx_count"]),
            fee_rate_sat_vb=str(raw["fee_rate_sat_vb"]),
            main_chain=bool(raw.get("main_chain", True)),
        )
        return (
            family,
            kind,
            bitcoin_payload,
            ChainPin(family=family, bitcoin=bitcoin_pin),
            subjects,
        )

    if family is SourceFamily.EVM:
        evm_pin = EvmPin(
            chain_id=int(raw["chain_id"]),
            block_number=int(raw["block_number"]),
            block_hash=str(raw["block_hash"]),
        )
        finality = FinalityState(str(raw["finality"]))
        evm_payload = EvmBlockObservation(
            pin=evm_pin,
            finality=finality,
            tx_count=int(raw["tx_count"]),
            gas_used=int(raw["gas_used"]),
        )
        return family, kind, evm_payload, ChainPin(family=family, evm=evm_pin), subjects

    if family is SourceFamily.SOLANA:
        solana_pin = SolanaPin(
            cluster=str(raw["cluster"]),
            slot=int(raw["slot"]),
            blockhash=str(raw["blockhash"]),
            commitment=SolanaCommitment(str(raw["commitment"])),
        )
        solana_payload = SolanaSlotObservation(
            pin=solana_pin,
            tx_count=int(raw["tx_count"]),
            fee_lamports=int(raw["fee_lamports"]),
        )
        return (
            family,
            kind,
            solana_payload,
            ChainPin(family=family, solana=solana_pin),
            subjects,
        )

    if family is SourceFamily.MARKET:
        instrument = InstrumentIdentity(
            venue=str(raw["venue"]),
            venue_symbol=str(raw["venue_symbol"]),
            base=str(raw["base"]),
            quote=str(raw["quote"]),
            instrument_type=raw["instrument_type"],
            tick_size=str(raw["tick_size"]),
            quantity_step=str(raw["quantity_step"]),
            multiplier=str(raw["multiplier"]),
        )
        market_payload = MarketTick(
            instrument=instrument,
            sequence=int(raw["sequence"]),
            bid=str(raw["bid"]),
            ask=str(raw["ask"]),
            last=str(raw["last"]),
            bid_size=str(raw["bid_size"]),
            ask_size=str(raw["ask_size"]),
            exchange_event_time=_parse_utc(str(raw["exchange_event_time"])),
        )
        return family, kind, market_payload, None, subjects

    if family is SourceFamily.GOVERNANCE:
        governance_payload = GovernanceRecord(
            proposal_id=str(raw["proposal_id"]),
            on_chain_execution_id=_optional_str(raw.get("on_chain_execution_id")),
            off_chain_discussion_id=_optional_str(raw.get("off_chain_discussion_id")),
            status=raw["status"],
            quorum_reached=bool(raw["quorum_reached"]),
            participation_bps=int(raw["participation_bps"]),
        )
        return family, kind, governance_payload, None, subjects

    if family is SourceFamily.GITHUB:
        github_payload = GitHubRecord(
            repository=str(raw["repository"]),
            event_type=raw["event_type"],
            cursor=str(raw["cursor"]),
            rate_limit_remaining=int(raw["rate_limit_remaining"]),
            rate_limit_reset_at=_parse_utc(str(raw["rate_limit_reset_at"])),
            ref=str(raw["ref"]),
            is_bot=bool(raw.get("is_bot", False)),
        )
        return family, kind, github_payload, None, subjects

    raise FixtureNormalizationError(f"unsupported fixture family: {family}")


def _optional_str(value: object) -> str | None:
    if value is None:
        return None
    return str(value)


def _parse_utc(value: str) -> datetime:
    normalized = value.replace("Z", "+00:00")
    parsed = datetime.fromisoformat(normalized)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)
