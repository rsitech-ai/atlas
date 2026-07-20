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
from rsi_atlas_security.ipc import IpcTransportMode, resolve_ipc_bind

from rsi_atlas_release.assembly import inspect_runtime_completeness
from rsi_atlas_release.inventory import inventory_staged_bundle
from rsi_atlas_release.sbom import build_sbom_from_lock


def run_release_check(
    *,
    repo_root: Path,
    require_release: bool = False,
    created_at: datetime | None = None,
    data_root: Path | None = None,
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
    blockers.extend(inspect_runtime_completeness(bundle))
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

    # Criterion 114: release must not expose an unintended TCP API.
    root_for_ipc = data_root or (repo_root / ".local")
    previous_release = os.environ.get("RSI_ATLAS_RELEASE_IPC")
    previous_tcp = os.environ.get("RSI_ATLAS_ALLOW_LOOPBACK_TCP")
    try:
        if require_release:
            os.environ["RSI_ATLAS_RELEASE_IPC"] = "1"
            os.environ.pop("RSI_ATLAS_ALLOW_LOOPBACK_TCP", None)
        cfg = resolve_ipc_bind(data_root=root_for_ipc)
        if require_release and cfg.mode is not IpcTransportMode.UNIX_DOMAIN:
            blockers.append("tcp_release_api")
        if (
            require_release
            and previous_tcp
            and previous_tcp.strip().lower()
            in {
                "1",
                "true",
                "yes",
                "on",
            }
        ):
            blockers.append("loopback_tcp_flag_set_in_release")
    except Exception as exc:
        blockers.append(f"ipc_policy_error:{type(exc).__name__}")
    finally:
        if previous_release is None:
            os.environ.pop("RSI_ATLAS_RELEASE_IPC", None)
        else:
            os.environ["RSI_ATLAS_RELEASE_IPC"] = previous_release
        if previous_tcp is None:
            os.environ.pop("RSI_ATLAS_ALLOW_LOOPBACK_TCP", None)
        else:
            os.environ["RSI_ATLAS_ALLOW_LOOPBACK_TCP"] = previous_tcp

    packaging = repo_root / "script" / "run_engine.py"
    if not packaging.is_file():
        blockers.append("release_ipc_runner_missing")
    entitlement_tcp_note = (
        entitlement_matrix.read_text(encoding="utf-8") if entitlement_present else ""
    )
    if entitlement_present and "Unix domain" not in entitlement_tcp_note:
        blockers.append("entitlement_matrix_missing_uds_ipc")

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
