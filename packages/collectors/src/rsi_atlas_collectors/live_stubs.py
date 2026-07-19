"""Fail-closed live collector stubs (no network I/O)."""

from __future__ import annotations

from rsi_atlas_contracts import LIVE_ACQUISITION_MODES, AcquisitionMode, SourceFamily

from rsi_atlas_collectors.errors import LiveCollectorBlocked


def require_offline_mode(mode: AcquisitionMode) -> None:
    if mode in LIVE_ACQUISITION_MODES:
        raise LiveCollectorBlocked(
            f"acquisition_mode={mode.value} is blocked_live_network; "
            "use fixture_import/filesystem_import/bundle_import"
        )


def refuse_live_collect(*, family: SourceFamily, mode: AcquisitionMode) -> None:
    require_offline_mode(mode)
    raise LiveCollectorBlocked(
        f"live collector for {family.value} is not implemented; offline fixtures only"
    )
