"""Release package tests."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from rsi_atlas_contracts import ReleaseClaim, SigningStatus
from rsi_atlas_release import build_sbom_from_lock, inventory_staged_bundle, run_release_check

NOW = datetime(2026, 7, 19, 17, 30, tzinfo=UTC)
ROOT = Path(__file__).resolve().parents[3]


def test_sbom_from_repo_lock() -> None:
    doc = build_sbom_from_lock(ROOT / "uv.lock", created_at=NOW)
    names = {component.name for component in doc.components}
    assert "pydantic" in names or "rsi-atlas-contracts" in names
    assert doc.bom_format == "CycloneDX"


def test_inventory_unsigned() -> None:
    inv = inventory_staged_bundle(ROOT / "dist" / "RSIAtlas.app")
    assert inv.signing_status is SigningStatus.UNSIGNED_DEVELOPMENT
    assert "unsigned" in inv.honesty_label


def test_release_check_fail_closed() -> None:
    report = run_release_check(repo_root=ROOT, require_release=True, created_at=NOW)
    assert report.release_ready is False
    assert report.claim is ReleaseClaim.RELEASE_CANDIDATE
    assert "notarization_blocked" in report.blockers
    assert "unsigned" in report.blockers


def test_development_check_not_ready() -> None:
    report = run_release_check(repo_root=ROOT, require_release=False, created_at=NOW)
    assert report.claim is ReleaseClaim.DEVELOPMENT_ONLY
    assert report.release_ready is False
    assert report.sbom_present is True
