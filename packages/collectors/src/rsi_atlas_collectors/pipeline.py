"""Offline fixture import pipeline: raw envelope before normalize."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from hashlib import sha256
from json import dumps, loads
from pathlib import Path
from uuid import UUID, uuid4

from rsi_atlas_contracts import (
    AcquisitionMode,
    ArtifactCommandContext,
    CollectorDefinition,
    CollectorLifecycle,
    EvmBlockObservation,
    FinalityState,
    Observation,
    ObservationHeader,
    ObservationQuality,
    ProviderQualityState,
    QuarantineRecord,
    RawEnvelope,
    SolanaCommitment,
    SolanaSlotObservation,
    SourceFamily,
    observation_id,
    raw_envelope_id,
)

from rsi_atlas_collectors.adapters import normalize_payload, normalizer_version, payload_kind_for
from rsi_atlas_collectors.errors import FixtureNormalizationError, QualityQuarantine
from rsi_atlas_collectors.live_stubs import require_offline_mode
from rsi_atlas_collectors.quality import evaluate_observation

FIXTURE_ROOT = Path(__file__).resolve().parents[2] / "fixtures"

_COLLECTOR_IDS: dict[SourceFamily, str] = {
    SourceFamily.BITCOIN: "bitcoin_fixture",
    SourceFamily.EVM: "evm_fixture",
    SourceFamily.SOLANA: "solana_fixture",
    SourceFamily.MARKET: "market_fixture",
    SourceFamily.GOVERNANCE: "governance_fixture",
    SourceFamily.GITHUB: "github_fixture",
}


@dataclass(frozen=True, slots=True)
class FixtureImportResult:
    envelope: RawEnvelope
    observation: Observation | None
    quarantine: QuarantineRecord | None
    payload_bytes: bytes


def collector_definition_for(family: SourceFamily) -> CollectorDefinition:
    return CollectorDefinition(
        collector_id=_COLLECTOR_IDS[family],
        source_family=family,
        provider="fixture",
        acquisition_mode=AcquisitionMode.FIXTURE_IMPORT,
        network_or_venue="offline",
        lifecycle=CollectorLifecycle.EXPERIMENTAL,
        schema_name=f"{family.value}_fixture_v1",
        rate_limit_per_minute=0,
        supports_backfill=False,
    )


def load_fixture_bytes(name: str) -> bytes:
    path = FIXTURE_ROOT / name
    if not path.is_file():
        raise FixtureNormalizationError(f"fixture not found: {name}")
    return path.read_bytes()


def import_fixture(
    *,
    context: ArtifactCommandContext,
    fixture_name: str,
    now: datetime | None = None,
    provider_quality: ProviderQualityState = ProviderQualityState.SINGLE_SOURCE,
) -> FixtureImportResult:
    require_offline_mode(AcquisitionMode.FIXTURE_IMPORT)
    stamped = now or datetime.now(tz=UTC)
    payload_bytes = load_fixture_bytes(fixture_name)
    raw = loads(payload_bytes.decode("utf-8"))
    if not isinstance(raw, dict):
        raise FixtureNormalizationError("fixture root must be an object")

    family, kind, payload, chain_pin, subjects = normalize_payload(raw)
    definition = collector_definition_for(family)
    payload_sha256 = sha256(payload_bytes).hexdigest()
    request_fingerprint = sha256(
        dumps(
            {"fixture": fixture_name, "collector": definition.collector_id},
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
    ).hexdigest()
    envelope = RawEnvelope(
        context=context,
        envelope_id=raw_envelope_id(
            collector_id=definition.collector_id,
            request_fingerprint=request_fingerprint,
            payload_sha256=payload_sha256,
        ),
        collector_id=definition.collector_id,
        provider=definition.provider,
        source_family=family,
        request_fingerprint=request_fingerprint,
        requested_at=stamped,
        received_at=stamped,
        event_time_hint=stamped,
        transport_status=200,
        content_type="application/json",
        payload_sha256=payload_sha256,
        payload_artifact_id=f"sha256:{payload_sha256}",
        payload_size_bytes=len(payload_bytes),
        source_schema=definition.schema_name,
        network_policy_decision="allow_offline",
        redacted_request_metadata={"fixture": fixture_name},
    )

    finality: FinalityState | SolanaCommitment | None = None
    if family is SourceFamily.BITCOIN:
        finality = FinalityState.FINALIZED
    elif isinstance(payload, EvmBlockObservation):
        finality = payload.finality
    elif isinstance(payload, SolanaSlotObservation):
        finality = payload.pin.commitment

    header = ObservationHeader(
        observation_id=observation_id(
            envelope_id=envelope.envelope_id,
            observation_type=kind,
            subject_ids=subjects,
            valid_time=stamped,
            normalizer_version=normalizer_version(),
        ),
        observation_type=kind,
        source_family=family,
        subject_ids=subjects,
        envelope_id=envelope.envelope_id,
        event_time=stamped,
        available_time=stamped,
        collected_time=stamped,
        normalized_time=stamped,
        valid_time=stamped,
        system_time=stamped,
        quality=ObservationQuality.VALID,
        finality=finality,
        provider_quality=provider_quality,
        normalizer_version=normalizer_version(),
        chain_pin=chain_pin,
    )
    observation = Observation(context=context, header=header, payload=payload)
    try:
        evaluate_observation(observation)
    except QualityQuarantine as error:
        quarantine = QuarantineRecord(
            context=context,
            quarantine_id=uuid4(),
            envelope_id=envelope.envelope_id,
            observation_id=observation.header.observation_id,
            reasons=error.reasons,
            severity="error",
            recorded_at=stamped,
        )
        return FixtureImportResult(
            envelope=envelope,
            observation=None,
            quarantine=quarantine,
            payload_bytes=payload_bytes,
        )
    return FixtureImportResult(
        envelope=envelope,
        observation=observation,
        quarantine=None,
        payload_bytes=payload_bytes,
    )


def assert_payload_kind_registry() -> None:
    """Ponytail self-check: every SourceFamily used by fixtures maps to a payload kind."""
    for family in (
        SourceFamily.BITCOIN,
        SourceFamily.EVM,
        SourceFamily.SOLANA,
        SourceFamily.MARKET,
        SourceFamily.GOVERNANCE,
        SourceFamily.GITHUB,
    ):
        assert payload_kind_for(family).value
        assert isinstance(uuid4(), UUID)
