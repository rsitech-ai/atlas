"""WebSocket live collectors — fail-closed until egress policy + calibration exist."""

from __future__ import annotations

from rsi_atlas_contracts import AcquisitionMode, SourceFamily

from rsi_atlas_collectors.errors import LiveCollectorBlocked


def refuse_websocket_stream(*, family: SourceFamily, origin: str) -> None:
    """Criterion: websocket_stream remains blocked without promoted egress policy."""
    del origin
    raise LiveCollectorBlocked(
        f"acquisition_mode={AcquisitionMode.WEBSOCKET_STREAM.value} is blocked for "
        f"{family.value}; use allowlisted HTTPS snapshot/poll or fixtures"
    )


__all__ = ["refuse_websocket_stream"]
