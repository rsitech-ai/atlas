import os
import stat
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest
from rsi_atlas_contracts import (
    AcquisitionMethod,
    AcquisitionRequest,
    AdmissionOutcome,
    ArtifactCommandContext,
    DocumentLifecycle,
)
from rsi_atlas_engine.ingestion import DocumentIngestionServices

CHECKED_AT = datetime(2026, 7, 18, 22, 30, tzinfo=UTC)


def test_real_ingestion_composition_uses_one_explicit_runtime_root(tmp_path: Path) -> None:
    conninfo = os.environ.get("RSI_ATLAS_TEST_DATABASE_URL")
    if conninfo is None:
        pytest.skip("real PostgreSQL integration URL is required")
    data_root = tmp_path / "runtime"
    data_root.mkdir(mode=0o700)
    source = Path(__file__).parent / "fixtures" / "minimal.pdf"
    context = ArtifactCommandContext(
        tenant_id=uuid4(),
        workspace_id=uuid4(),
        actor_id=uuid4(),
        trace_id=uuid4(),
    )
    acquisition_id = uuid4()
    request = AcquisitionRequest(
        acquisition_id=acquisition_id,
        method=AcquisitionMethod.MANUAL_CLI,
        original_filename=source.name,
        source_locator=f"manual-import:{acquisition_id}",
        declared_media_type="application/pdf",
        collector_version="integration-0.1.0",
    )

    services = DocumentIngestionServices.from_environment(
        environ={"RSI_ATLAS_DATA_ROOT": str(data_root)},
        database_conninfo=conninfo,
        clock=lambda: CHECKED_AT,
    )
    staged = services.staging_area.stage_file(source)
    try:
        record = services.admission_service.admit_staged(
            context=context,
            request=request,
            staged_path=staged.path,
            staged_evidence=staged.evidence,
        )
    finally:
        staged.cleanup()

    assert record.lifecycle is DocumentLifecycle.AWAITING_REVIEW
    assert record.outcome is AdmissionOutcome.QUARANTINE_FOR_REVIEW
    assert record.recorded_at == CHECKED_AT
    assert (data_root / "artifacts" / "sha256" / record.artifact.digest[:2]).is_dir()
    staging_root = data_root / "staging" / "imports"
    assert stat.S_IMODE(staging_root.stat().st_mode) == 0o700
    assert tuple(staging_root.iterdir()) == ()


def test_api_and_cli_compositions_use_independent_leased_staging_roots(
    tmp_path: Path,
) -> None:
    conninfo = os.environ.get("RSI_ATLAS_TEST_DATABASE_URL")
    if conninfo is None:
        pytest.skip("real PostgreSQL integration URL is required")
    data_root = tmp_path / "runtime"
    data_root.mkdir(mode=0o700)

    api_services = DocumentIngestionServices.from_environment(
        environ={"RSI_ATLAS_DATA_ROOT": str(data_root)},
        database_conninfo=conninfo,
        staging_namespace="api",
    )
    cli_services = DocumentIngestionServices.from_environment(
        environ={"RSI_ATLAS_DATA_ROOT": str(data_root)},
        database_conninfo=conninfo,
        staging_namespace="cli",
    )

    assert api_services.staging_area is not cli_services.staging_area
    assert (data_root / "staging" / "imports").is_dir()
    assert (data_root / "staging" / "cli-imports").is_dir()
