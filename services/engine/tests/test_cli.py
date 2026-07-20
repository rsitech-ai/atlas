import json
import os
import subprocess
import sys
from datetime import UTC, datetime
from io import StringIO
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from uuid import UUID

from rsi_atlas_contracts import (
    AdmissionOutcome,
    ArtifactDescriptor,
    ArtifactID,
    DocumentAdmissionRecord,
    DocumentLifecycle,
    HealthState,
    PDFSafetyProfile,
    SafetyCheckState,
    SystemStatus,
)
from rsi_atlas_engine.cli import main
from rsi_atlas_engine.import_staging import ImportStagingArea
from rsi_atlas_ingestion import StagedPDFEvidence


def test_python_module_entrypoint_exposes_cli_without_source_path_fallback() -> None:
    environment = os.environ.copy()
    environment.pop("PYTHONPATH", None)

    result = subprocess.run(
        [sys.executable, "-I", "-s", "-m", "rsi_atlas_engine", "--help"],
        cwd=Path("/tmp"),
        env=environment,
        check=False,
        capture_output=True,
        text=True,
        timeout=10,
    )

    assert result.returncode == 0, result.stderr
    assert "RSI Atlas local tooling" in result.stdout


def _fixture_status() -> SystemStatus:
    root = Path(__file__).resolve().parents[3]
    fixture = root / "apps/macos/Tests/RSIAtlasCoreTests/Fixtures/system_status_v1_1.json"
    return SystemStatus.model_validate_json(fixture.read_text())


def _with_state(state: HealthState) -> SystemStatus:
    baseline = _fixture_status()
    component = baseline.components[0].model_copy(
        update={
            "state": state,
            "summary": f"Engine runtime is {state.value}.",
            "remediation": "Repair the local runtime."
            if state is not HealthState.HEALTHY
            else None,
        }
    )
    components = (component, *baseline.components[1:])
    priority = {
        HealthState.HEALTHY: 0,
        HealthState.DEGRADED: 1,
        HealthState.REPAIRABLE: 2,
        HealthState.BLOCKED: 3,
        HealthState.UNSAFE: 4,
    }
    aggregate = max(components, key=lambda item: priority[item.state]).state
    return SystemStatus.model_validate(
        {
            **baseline.model_dump(mode="python"),
            "state": aggregate,
            "components": components,
        }
    )


def test_doctor_json_emits_all_phase_one_components() -> None:
    expected = _fixture_status()
    output = StringIO()

    exit_code = main(
        ["doctor", "--json"],
        stdout=output,
        status_factory=lambda: expected,
    )

    payload = json.loads(output.getvalue())
    assert exit_code == 0
    assert payload == expected.model_dump(mode="json")
    assert {item["component_id"] for item in payload["components"]} == {
        "engine_runtime",
        "database",
        "artifact_store",
        "offline_policy",
        "trace_store",
        "resource_policy",
        "model_registry",
        "contract_api",
    }


def test_doctor_text_displays_remediation_and_degraded_is_operational() -> None:
    output = StringIO()

    exit_code = main(
        ["doctor"],
        stdout=output,
        status_factory=_fixture_status,
    )

    assert exit_code == 0
    assert "RSI Atlas: degraded (offline)" in output.getvalue()
    assert (
        "Remediation: Select and admit a provider only after governed evaluation "
        "and owner approval." in output.getvalue()
    )


def test_doctor_returns_failure_for_actionable_status() -> None:
    output = StringIO()

    exit_code = main(
        ["doctor"],
        stdout=output,
        status_factory=lambda: _with_state(HealthState.BLOCKED),
    )

    assert exit_code == 1
    assert "RSI Atlas: blocked (offline)" in output.getvalue()


class _FakeAdmissionService:
    def __init__(self, *, error: Exception | None = None) -> None:
        self.error = error
        self.calls: list[dict[str, Any]] = []

    def admit_staged(self, **call: Any) -> DocumentAdmissionRecord:
        self.calls.append(call)
        if self.error is not None:
            raise self.error
        evidence: StagedPDFEvidence = call["staged_evidence"]
        descriptor = ArtifactDescriptor(
            artifact_id=ArtifactID(f"sha256:{evidence.digest}"),
            digest=evidence.digest,
            size_bytes=evidence.size_bytes,
            media_type="application/pdf",
        )
        return DocumentAdmissionRecord(
            context=call["context"],
            request=call["request"],
            artifact=descriptor,
            profile=PDFSafetyProfile(
                artifact_id=descriptor.artifact_id,
                digest=descriptor.digest,
                size_bytes=descriptor.size_bytes,
                header_version="1.7",
                eof_marker_present=True,
                page_marker_count=None,
                mime_signature_consistency=SafetyCheckState.PASS,
                size_limit=SafetyCheckState.PASS,
                page_count_limit=SafetyCheckState.UNKNOWN,
                encryption_password_state=SafetyCheckState.UNKNOWN,
                malformed_structure=SafetyCheckState.UNKNOWN,
                embedded_files=SafetyCheckState.UNKNOWN,
                active_actions=SafetyCheckState.UNKNOWN,
                suspicious_references=SafetyCheckState.UNKNOWN,
                decompression_ratio=SafetyCheckState.UNKNOWN,
                source_policy=SafetyCheckState.PASS,
                available_disk=SafetyCheckState.PASS,
                inspected_at=datetime(2026, 7, 18, 22, 0, tzinfo=UTC),
            ),
            lifecycle=DocumentLifecycle.AWAITING_REVIEW,
            outcome=AdmissionOutcome.QUARANTINE_FOR_REVIEW,
            reason_codes=("required_check_unknown",),
            recorded_at=datetime(2026, 7, 18, 22, 0, tzinfo=UTC),
        )


def _import_arguments(source: Path) -> list[str]:
    return [
        "import-pdf",
        str(source),
        "--tenant-id",
        "11111111-1111-4111-8111-111111111111",
        "--workspace-id",
        "22222222-2222-4222-8222-222222222222",
        "--actor-id",
        "33333333-3333-4333-8333-333333333333",
        "--trace-id",
        "44444444-4444-4444-8444-444444444444",
        "--acquisition-id",
        "55555555-5555-4555-8555-555555555555",
        "--json",
    ]


def _ingestion_fixture(tmp_path: Path, service: _FakeAdmissionService) -> tuple[Any, Path]:
    staging_root = tmp_path / "staging"
    staging_root.mkdir(mode=0o700)
    staging_root.chmod(0o700)
    return (
        SimpleNamespace(
            admission_service=service,
            staging_area=ImportStagingArea(staging_root),
        ),
        staging_root,
    )


def test_import_pdf_emits_durable_json_and_cleans_staging(tmp_path: Path) -> None:
    source = tmp_path / "protocol-paper.pdf"
    source.write_bytes(b"%PDF-1.7\n%%EOF\n")
    source.chmod(0o600)
    service = _FakeAdmissionService()
    services, staging_root = _ingestion_fixture(tmp_path, service)
    output = StringIO()
    errors = StringIO()

    exit_code = main(
        _import_arguments(source),
        stdout=output,
        stderr=errors,
        ingestion_factory=lambda: services,
    )

    assert exit_code == 0
    record = DocumentAdmissionRecord.model_validate_json(output.getvalue())
    assert record.outcome is AdmissionOutcome.QUARANTINE_FOR_REVIEW
    assert service.calls[0]["request"].method.value == "manual_cli"
    assert service.calls[0]["request"].original_filename == source.name
    assert service.calls[0]["context"].workspace_id == UUID("22222222-2222-4222-8222-222222222222")
    assert errors.getvalue() == ""
    assert tuple(staging_root.iterdir()) == ()


def test_import_pdf_rejects_symlink_without_leaking_source_path(tmp_path: Path) -> None:
    source = tmp_path / "private-research-paper.pdf"
    source.write_bytes(b"%PDF-1.7\n%%EOF\n")
    link = tmp_path / "link.pdf"
    link.symlink_to(source)
    service = _FakeAdmissionService()
    services, staging_root = _ingestion_fixture(tmp_path, service)
    output = StringIO()
    errors = StringIO()

    exit_code = main(
        _import_arguments(link),
        stdout=output,
        stderr=errors,
        ingestion_factory=lambda: services,
    )

    assert exit_code == 2
    assert output.getvalue() == ""
    assert errors.getvalue() == "PDF import failed: source is missing or unsafe.\n"
    assert str(source) not in errors.getvalue()
    assert service.calls == []
    assert tuple(staging_root.iterdir()) == ()


def test_import_pdf_sanitizes_persistence_failure_and_cleans_staging(tmp_path: Path) -> None:
    source = tmp_path / "protocol-paper.pdf"
    source.write_bytes(b"%PDF-1.7\n%%EOF\n")
    service = _FakeAdmissionService(error=RuntimeError("secret database details"))
    services, staging_root = _ingestion_fixture(tmp_path, service)
    output = StringIO()
    errors = StringIO()

    exit_code = main(
        _import_arguments(source),
        stdout=output,
        stderr=errors,
        ingestion_factory=lambda: services,
    )

    assert exit_code == 3
    assert output.getvalue() == ""
    assert errors.getvalue() == "PDF import failed: durable admission is unavailable.\n"
    assert "secret" not in errors.getvalue()
    assert len(service.calls) == 1
    assert tuple(staging_root.iterdir()) == ()
