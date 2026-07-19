"""Optional live HTTPS collect behind NetworkPolicy (deny-by-default)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from hashlib import sha256
from json import dumps, loads
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen
from uuid import uuid4

from rsi_atlas_contracts import (
    AcquisitionMode,
    ArtifactCommandContext,
    CollectorDefinition,
    CollectorLifecycle,
    RawEnvelope,
    SourceFamily,
    raw_envelope_id,
)
from rsi_atlas_security.network_policy import NetworkPolicy, ProcessRole

from rsi_atlas_collectors.errors import LiveCollectorBlocked
from rsi_atlas_collectors.live_stubs import LIVE_HTTP_MODES

_COLLECTOR_IDS: dict[SourceFamily, str] = {
    SourceFamily.BITCOIN: "bitcoin_live_https",
    SourceFamily.EVM: "evm_live_https",
    SourceFamily.SOLANA: "solana_live_https",
    SourceFamily.MARKET: "market_live_https",
    SourceFamily.GOVERNANCE: "governance_live_https",
    SourceFamily.GITHUB: "github_live_https",
}


@dataclass(frozen=True, slots=True)
class LiveCollectResult:
    envelope: RawEnvelope
    payload_bytes: bytes
    payload_json: dict[str, object]


def live_collector_definition(*, family: SourceFamily, origin: str) -> CollectorDefinition:
    return CollectorDefinition(
        collector_id=_COLLECTOR_IDS[family],
        source_family=family,
        provider="user_supplied_https",
        acquisition_mode=AcquisitionMode.ON_DEMAND,
        network_or_venue=origin,
        lifecycle=CollectorLifecycle.EXPERIMENTAL,
        schema_name=f"{family.value}_live_v1",
        rate_limit_per_minute=30,
        supports_backfill=False,
        allowlist=(origin,),
    )


def collect_live_json(
    *,
    family: SourceFamily,
    mode: AcquisitionMode,
    origin: str,
    path: str,
    context: ArtifactCommandContext,
    policy: NetworkPolicy,
    timeout_seconds: float = 10.0,
    body: bytes | None = None,
) -> LiveCollectResult:
    """Fetch JSON from a user-supplied HTTPS origin allowlisted by policy.

    No baked-in API keys. Origin must be canonical https://host:port.
    """
    if mode not in LIVE_HTTP_MODES:
        raise LiveCollectorBlocked(
            f"acquisition_mode={mode.value} is blocked_live_network for HTTPS slice; "
            "use snapshot/incremental_poll/on_demand with allowlisted origin"
        )
    parsed = urlsplit(origin)
    if (
        parsed.scheme != "https"
        or parsed.hostname is None
        or parsed.port is None
        or parsed.path
        or parsed.query
        or parsed.fragment
        or parsed.username
        or parsed.password
    ):
        raise LiveCollectorBlocked("origin must be canonical https://host:port")
    decision = policy.authorize(
        role=ProcessRole.COLLECTOR,
        scheme=parsed.scheme,
        host=parsed.hostname,
        port=parsed.port,
    )
    if not decision.allowed:
        raise LiveCollectorBlocked(
            f"deny_live: {decision.reason}; supply allowlisted https://host:port origin"
        )
    if not path.startswith("/"):
        raise LiveCollectorBlocked("path must start with /")
    url = f"{origin}{path}"
    request = Request(
        url,
        data=body,
        method="POST" if body is not None else "GET",
        headers={"Accept": "application/json", "User-Agent": "rsi-atlas-collector/0.1"},
    )
    try:
        with urlopen(request, timeout=timeout_seconds) as response:
            payload = response.read()
            status = int(getattr(response, "status", 200))
    except HTTPError as error:
        raise LiveCollectorBlocked(f"live HTTP error: {error.code}") from error
    except URLError as error:
        raise LiveCollectorBlocked(f"live network error: {error.reason}") from error
    if status >= 400:
        raise LiveCollectorBlocked(f"live HTTP status {status}")
    try:
        parsed_json = loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as error:
        raise LiveCollectorBlocked("live response was not JSON") from error
    if not isinstance(parsed_json, dict):
        raise LiveCollectorBlocked("live JSON root must be an object")
    stamped = datetime.now(tz=UTC)
    definition = live_collector_definition(family=family, origin=origin)
    payload_sha256 = sha256(payload).hexdigest()
    request_fingerprint = sha256(
        dumps(
            {"origin": origin, "path": path, "collector": definition.collector_id},
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
        transport_status=status,
        content_type="application/json",
        payload_sha256=payload_sha256,
        payload_artifact_id=f"sha256:{payload_sha256}",
        payload_size_bytes=len(payload),
        source_schema=definition.schema_name,
        network_policy_decision="allow_monitored",
        redacted_request_metadata={"origin": origin, "path": path, "trace": str(uuid4())},
    )
    return LiveCollectResult(envelope=envelope, payload_bytes=payload, payload_json=parsed_json)


__all__ = [
    "LiveCollectResult",
    "collect_live_json",
    "live_collector_definition",
]
