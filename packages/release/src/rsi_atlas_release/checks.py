"""Fail-closed release checks without Apple signing secrets."""

from __future__ import annotations

import os
from datetime import UTC, datetime
from pathlib import Path

from rsi_atlas_contracts import (
    ReleaseCheckReport,
    ReleaseClaim,
    SigningStatus,
    release_check_id,
)

from rsi_atlas_release.inventory import inventory_staged_bundle
from rsi_atlas_release.sbom import build_sbom_from_lock


def run_release_check(
    *,
    repo_root: Path,
    require_release: bool = False,
    created_at: datetime | None = None,
) -> ReleaseCheckReport:
    """Always report unsigned/notarization_blocked unless secrets exist (they don't in CI)."""
    now = created_at or datetime.now(tz=UTC)
    lock_path = repo_root / "uv.lock"
    sbom_present = False
    sbom_path = repo_root / "dist" / "sbom.cdx.json"
    if lock_path.is_file():
        sbom = build_sbom_from_lock(lock_path, created_at=now)
        sbom_path.parent.mkdir(parents=True, exist_ok=True)
        sbom_path.write_bytes(sbom.model_dump_json(indent=2).encode("utf-8"))
        sbom_present = True
    bundle = repo_root / "dist" / "RSIAtlas.app"
    inventory = inventory_staged_bundle(bundle)
    signing_identity = os.environ.get("RSI_ATLAS_SIGNING_IDENTITY", "").strip()
    notarization_key = os.environ.get("RSI_ATLAS_NOTARY_KEY", "").strip()
    blockers: list[str] = []
    signing_status = SigningStatus.UNSIGNED_DEVELOPMENT
    notarization_status = SigningStatus.NOTARIZATION_BLOCKED
    if not signing_identity:
        blockers.append("unsigned")
        blockers.append("signing_identity_missing")
    else:
        # Secrets present is still not proof of nested signed artifact in this slice.
        blockers.append("signed_artifact_unverified")
        signing_status = SigningStatus.UNSIGNED_DEVELOPMENT
    if not notarization_key:
        blockers.append("notarization_blocked")
    else:
        blockers.append("notarization_unverified")
    if not sbom_present:
        blockers.append("sbom_missing")
    entitlement_matrix = repo_root / "docs" / "release" / "entitlement-matrix.md"
    entitlement_present = entitlement_matrix.is_file()
    if not entitlement_present:
        blockers.append("entitlement_matrix_missing")
    governance = repo_root / "docs" / "dependency-governance"
    if not (governance / "embedding-model-approval.md").is_file():
        blockers.append("embedding_governance_missing")
    if (
        inventory.signing_status is SigningStatus.UNSIGNED_DEVELOPMENT
        and "unsigned" not in blockers
    ):
        blockers.append("unsigned")
    claim = ReleaseClaim.RELEASE_CANDIDATE if require_release else ReleaseClaim.DEVELOPMENT_ONLY
    release_ready = False
    if require_release:
        # Hard fail-closed: never ready without verified signing+notarization evidence.
        release_ready = False
    return ReleaseCheckReport(
        report_id=release_check_id(claim=claim, created_at=now),
        claim=claim,
        signing_status=signing_status,
        notarization_status=notarization_status,
        sbom_present=sbom_present,
        entitlement_matrix_present=entitlement_present,
        zero_egress_recorded=True,
        blockers=tuple(dict.fromkeys(blockers)),
        release_ready=release_ready,
        created_at=now,
    )
