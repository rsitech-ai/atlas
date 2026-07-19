"""Market sequence continuity checks (fixture path)."""

from __future__ import annotations

from rsi_atlas_contracts import MarketTick

from rsi_atlas_collectors.errors import MarketSequenceError


def require_contiguous_sequence(*, previous: MarketTick | None, current: MarketTick) -> None:
    if previous is None:
        return
    expected = previous.sequence + 1
    if current.sequence != expected:
        raise MarketSequenceError(
            f"market sequence gap: expected {expected}, got {current.sequence}; "
            "discard buffer and resnapshot"
        )
