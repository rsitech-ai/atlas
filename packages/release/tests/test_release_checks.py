"""Release package tests."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from rsi_atlas_contracts import ReleaseClaim, SigningStatus
from rsi_atlas_release import (
    REQUIRED_RUNTIME_COMPONENTS,
    build_sbom_from_lock,
    inspect_runtime_completeness,
    inventory_staged_bundle,
    run_release_check,
)

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
    assert report.entitlement_matrix_present is True
    assert "notarization_blocked" in report.blockers


def test_runtime_completeness_reports_exact_missing_components(tmp_path: Path) -> None:
    bundle = tmp_path / "RSIAtlas.app"
    executable = bundle / "Contents" / "MacOS" / "RSIAtlas"
    executable.parent.mkdir(parents=True)
    executable.write_bytes(b"native-shell")

    assert inspect_runtime_completeness(bundle) == (
        "embedded_python_missing",
        "engine_launcher_missing",
        "postgresql_missing",
        "pgvector_missing",
    )


def test_runtime_completeness_accepts_every_required_component(tmp_path: Path) -> None:
    bundle = tmp_path / "RSIAtlas.app"
    for relative_path in REQUIRED_RUNTIME_COMPONENTS.values():
        component = bundle / relative_path
        component.parent.mkdir(parents=True, exist_ok=True)
        component.write_bytes(b"\xcf\xfa\xed\xfe" + b"release-component")
        component.chmod(0o700)

    assert inspect_runtime_completeness(bundle) == ()


def test_runtime_completeness_rejects_non_mach_o_placeholders(tmp_path: Path) -> None:
    bundle = tmp_path / "RSIAtlas.app"
    for relative_path in REQUIRED_RUNTIME_COMPONENTS.values():
        component = bundle / relative_path
        component.parent.mkdir(parents=True, exist_ok=True)
        component.write_bytes(b"not-a-runtime-binary")
        component.chmod(0o700)

    assert inspect_runtime_completeness(bundle) == tuple(REQUIRED_RUNTIME_COMPONENTS)


def test_runtime_completeness_requires_executable_runtime_entrypoints(tmp_path: Path) -> None:
    bundle = tmp_path / "RSIAtlas.app"
    for relative_path in REQUIRED_RUNTIME_COMPONENTS.values():
        component = bundle / relative_path
        component.parent.mkdir(parents=True, exist_ok=True)
        component.write_bytes(b"\xcf\xfa\xed\xfe" + b"release-component")
        component.chmod(0o600)

    assert inspect_runtime_completeness(bundle) == (
        "embedded_python_missing",
        "engine_launcher_missing",
        "postgresql_missing",
    )


def test_runtime_completeness_rejects_symlinked_components(tmp_path: Path) -> None:
    bundle = tmp_path / "RSIAtlas.app"
    external = tmp_path / "external-runtime-component"
    external.write_bytes(b"outside-the-bundle")
    for relative_path in REQUIRED_RUNTIME_COMPONENTS.values():
        component = bundle / relative_path
        component.parent.mkdir(parents=True, exist_ok=True)
        component.symlink_to(external)

    assert inspect_runtime_completeness(bundle) == tuple(REQUIRED_RUNTIME_COMPONENTS)


def test_release_check_propagates_runtime_component_blockers(tmp_path: Path) -> None:
    (tmp_path / "uv.lock").write_bytes((ROOT / "uv.lock").read_bytes())
    entitlement = tmp_path / "docs" / "release" / "entitlement-matrix.md"
    entitlement.parent.mkdir(parents=True)
    entitlement.write_text("Release transport: Unix domain socket.\n", encoding="utf-8")
    governance = tmp_path / "docs" / "dependency-governance" / "embedding-model-approval.md"
    governance.parent.mkdir(parents=True)
    governance.write_text("approved\n", encoding="utf-8")
    runner = tmp_path / "script" / "run_engine.py"
    runner.parent.mkdir(parents=True)
    runner.write_text("# release IPC runner\n", encoding="utf-8")
    executable = tmp_path / "dist" / "RSIAtlas.app" / "Contents" / "MacOS" / "RSIAtlas"
    executable.parent.mkdir(parents=True)
    executable.write_bytes(b"native-shell")

    report = run_release_check(repo_root=tmp_path, require_release=True, created_at=NOW)

    assert set(inspect_runtime_completeness(executable.parents[2])).issubset(report.blockers)
