"""WebSocket collector fail-closed tests."""

from __future__ import annotations

import pytest
from rsi_atlas_collectors import LiveCollectorBlocked, refuse_websocket_stream
from rsi_atlas_contracts import SourceFamily


def test_websocket_refused() -> None:
    with pytest.raises(LiveCollectorBlocked, match="websocket_stream"):
        refuse_websocket_stream(family=SourceFamily.BITCOIN, origin="wss://example.invalid")
