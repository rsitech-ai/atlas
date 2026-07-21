from pathlib import Path

import pytest
from rsi_atlas_engine.safe_mode import runtime_data_root


def test_safe_mode_data_root_defaults_to_application_support(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))

    assert runtime_data_root(environ={}) == (
        tmp_path / "Library" / "Application Support" / "ai.rsitech.RSIAtlas"
    )


def test_safe_mode_data_root_honors_explicit_runtime_root(tmp_path: Path) -> None:
    explicit = tmp_path / "data"

    assert runtime_data_root(environ={"RSI_ATLAS_DATA_ROOT": str(explicit)}) == explicit
