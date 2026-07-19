"""Safe Mode capability mask."""

from __future__ import annotations

from datetime import datetime

from rsi_atlas_contracts import SAFE_MODE_DISABLED_CAPABILITIES, SafeModeCapability, SafeModeState


class SafeModeController:
    def __init__(self) -> None:
        self._state = SafeModeState(active=False, disabled_capabilities=frozenset())

    @property
    def state(self) -> SafeModeState:
        return self._state

    def enter(self, *, reason: str, entered_at: datetime) -> SafeModeState:
        self._state = SafeModeState(
            active=True,
            disabled_capabilities=SAFE_MODE_DISABLED_CAPABILITIES,
            entered_at=entered_at,
            reason=reason,
        )
        return self._state

    def exit(self) -> SafeModeState:
        self._state = SafeModeState(active=False, disabled_capabilities=frozenset())
        return self._state

    def is_disabled(self, capability: SafeModeCapability) -> bool:
        return self._state.active and capability in self._state.disabled_capabilities
