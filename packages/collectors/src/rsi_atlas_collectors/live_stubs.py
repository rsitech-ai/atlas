"""Fail-closed live collector stubs (default) with optional monitored gate."""

from __future__ import annotations

from rsi_atlas_contracts import LIVE_ACQUISITION_MODES, AcquisitionMode, SourceFamily

from rsi_atlas_collectors.errors import LiveCollectorBlocked

LIVE_HTTP_MODES = frozenset(
    {
        AcquisitionMode.SNAPSHOT,
        AcquisitionMode.INCREMENTAL_POLL,
        AcquisitionMode.ON_DEMAND,
    }
)


def require_offline_mode(mode: AcquisitionMode) -> None:
    if mode in LIVE_ACQUISITION_MODES:
        raise LiveCollectorBlocked(
            f"acquisition_mode={mode.value} is blocked_live_network; "
            "use fixture_import/filesystem_import/bundle_import "
            "or collect_live_json with NetworkPolicy.monitored allowlist"
        )


def refuse_live_collect(*, family: SourceFamily, mode: AcquisitionMode) -> None:
    """Default refuse when no monitored policy/origin is configured."""
    require_offline_mode(mode)
    raise LiveCollectorBlocked(
        f"live collector for {family.value} requires explicit allowlisted origin; "
        "offline fixtures only by default"
    )
