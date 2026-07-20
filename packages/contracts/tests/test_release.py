"""Strict Phase 6 release contract tests."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError
from rsi_atlas_contracts.release import (
    PackageInventory,
    ReleaseCheckReport,
    ReleaseClaim,
    SbomComponent,
    SbomDocument,
    SbomFile,
    SigningStatus,
    release_check_id,
    sbom_id,
)

NOW = datetime(2026, 7, 19, 17, 0, tzinfo=UTC)
LOCK = "d" * 64


def test_unsigned_inventory_requires_honesty_label() -> None:
    inv = PackageInventory(
        bundle_path="dist/RSIAtlas.app",
        signing_status=SigningStatus.UNSIGNED_DEVELOPMENT,
        python_embedded=False,
        honesty_label="unsigned_development",
        component_count=1,
    )
    assert inv.signing_status is SigningStatus.UNSIGNED_DEVELOPMENT
    embedded = PackageInventory(
        bundle_path="dist/RSIAtlas.app",
        signing_status=SigningStatus.UNSIGNED_DEVELOPMENT,
        python_embedded=True,
        honesty_label="unsigned_with_embedded_runtime",
        component_count=2,
    )
    assert embedded.python_embedded is True
    with pytest.raises(ValidationError, match="unsigned"):
        PackageInventory(
            bundle_path="dist/RSIAtlas.app",
            signing_status=SigningStatus.UNSIGNED_DEVELOPMENT,
            python_embedded=False,
            honesty_label="production_ready",
            component_count=1,
        )


def test_release_candidate_cannot_claim_ready_without_signing() -> None:
    rid = release_check_id(claim=ReleaseClaim.RELEASE_CANDIDATE, created_at=NOW)
    report = ReleaseCheckReport(
        report_id=rid,
        claim=ReleaseClaim.RELEASE_CANDIDATE,
        signing_status=SigningStatus.UNSIGNED_DEVELOPMENT,
        notarization_status=SigningStatus.NOTARIZATION_BLOCKED,
        sbom_present=True,
        entitlement_matrix_present=False,
        zero_egress_recorded=True,
        blockers=("unsigned", "notarization_blocked"),
        release_ready=False,
        created_at=NOW,
    )
    assert report.release_ready is False
    with pytest.raises(ValidationError, match=r"Developer ID|notarization|signing"):
        ReleaseCheckReport(
            report_id=rid,
            claim=ReleaseClaim.RELEASE_CANDIDATE,
            signing_status=SigningStatus.UNSIGNED_DEVELOPMENT,
            notarization_status=SigningStatus.NOTARIZATION_BLOCKED,
            sbom_present=True,
            entitlement_matrix_present=True,
            zero_egress_recorded=True,
            blockers=(),
            release_ready=True,
            created_at=NOW,
        )


def test_sbom_document_shape() -> None:
    doc = SbomDocument(
        sbom_id=sbom_id(source_lock_hash=LOCK, created_at=NOW),
        bom_format="CycloneDX",
        spec_version="1.5",
        components=(
            SbomComponent(
                name="rsi-atlas-contracts",
                version="0.1.0",
                sha256=LOCK,
                license_files=("Contents/Resources/Legal/LICENSE",),
            ),
        ),
        created_at=NOW,
        source_lock_hash=LOCK,
        artifact_tree_sha256=LOCK,
        files=(SbomFile(path="Contents/MacOS/RSIAtlas", sha256=LOCK),),
        excluded_paths=("Contents/Resources/sbom.cdx.json",),
    )
    assert doc.bom_format == "CycloneDX"
    assert doc.files[0].sha256 == LOCK


@pytest.mark.parametrize("path", ("/absolute", "../escape", "Contents/../escape"))
def test_sbom_rejects_non_bundle_relative_paths(path: str) -> None:
    with pytest.raises(ValidationError, match="bundle-relative"):
        SbomFile(path=path, sha256=LOCK)
