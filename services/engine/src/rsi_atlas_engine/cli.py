import argparse
import sys
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import NoReturn, Protocol, TextIO
from uuid import UUID

from pydantic import ValidationError
from rsi_atlas_contracts import (
    AcquisitionMethod,
    AcquisitionRequest,
    ArtifactCommandContext,
    DocumentAdmissionRecord,
    HealthState,
    SystemStatus,
)
from rsi_atlas_ingestion import StagedPDFEvidence

from rsi_atlas_engine.import_staging import ImportStagingArea, ImportStagingError
from rsi_atlas_engine.ingestion import DocumentIngestionServices
from rsi_atlas_engine.runtime import RuntimeServices


class _AdmissionServicePort(Protocol):
    def admit_staged(
        self,
        *,
        context: ArtifactCommandContext,
        request: AcquisitionRequest,
        staged_path: Path,
        staged_evidence: StagedPDFEvidence,
    ) -> DocumentAdmissionRecord: ...


class _DocumentIngestionPort(Protocol):
    @property
    def admission_service(self) -> _AdmissionServicePort: ...

    @property
    def staging_area(self) -> ImportStagingArea: ...


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="atlas", description="RSI Atlas local tooling")
    commands = parser.add_subparsers(dest="command", required=True)
    doctor = commands.add_parser("doctor", help="Inspect the local RSI Atlas runtime")
    doctor.add_argument("--json", action="store_true", help="Emit the versioned JSON contract")
    import_pdf = commands.add_parser("import-pdf", help="Admit one local PDF as evidence")
    import_pdf.add_argument("file", type=Path, metavar="FILE")
    import_pdf.add_argument("--tenant-id", required=True)
    import_pdf.add_argument("--workspace-id", required=True)
    import_pdf.add_argument("--actor-id", required=True)
    import_pdf.add_argument("--trace-id", required=True)
    import_pdf.add_argument("--acquisition-id", required=True)
    import_pdf.add_argument(
        "--collector-version",
        default="cli-0.1.0",
        help="Collector version recorded with the immutable acquisition",
    )
    import_pdf.add_argument("--json", action="store_true", help="Emit the admission JSON contract")
    return parser


def main(
    argv: Sequence[str] | None = None,
    *,
    stdout: TextIO = sys.stdout,
    stderr: TextIO = sys.stderr,
    status_factory: Callable[[], SystemStatus] | None = None,
    ingestion_factory: Callable[[], _DocumentIngestionPort] | None = None,
) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "import-pdf":
        return _import_pdf(
            args,
            stdout=stdout,
            stderr=stderr,
            ingestion_factory=ingestion_factory
            or (lambda: DocumentIngestionServices.from_environment(staging_namespace="cli")),
        )

    status = (status_factory or RuntimeServices.from_environment().status)()

    if args.json:
        print(status.model_dump_json(indent=2), file=stdout)
    else:
        print(f"RSI Atlas: {status.state.value} ({status.profile.value})", file=stdout)
        for component in status.components:
            print(
                f"- {component.title}: {component.state.value} — {component.summary}",
                file=stdout,
            )
            if component.remediation is not None:
                print(f"  Remediation: {component.remediation}", file=stdout)

    return 0 if status.state in {HealthState.HEALTHY, HealthState.DEGRADED} else 1


def _import_pdf(
    args: argparse.Namespace,
    *,
    stdout: TextIO,
    stderr: TextIO,
    ingestion_factory: Callable[[], _DocumentIngestionPort],
) -> int:
    try:
        acquisition_id = UUID(args.acquisition_id)
        context = ArtifactCommandContext(
            tenant_id=UUID(args.tenant_id),
            workspace_id=UUID(args.workspace_id),
            actor_id=UUID(args.actor_id),
            trace_id=UUID(args.trace_id),
        )
        request = AcquisitionRequest(
            acquisition_id=acquisition_id,
            method=AcquisitionMethod.MANUAL_CLI,
            original_filename=args.file.name,
            source_locator=f"manual-import:{acquisition_id}",
            declared_media_type="application/pdf",
            collector_version=args.collector_version,
        )
    except (ValidationError, ValueError, AttributeError):
        print("PDF import failed: metadata is invalid.", file=stderr)
        return 2

    try:
        services = ingestion_factory()
    except Exception:
        print("PDF import failed: durable admission is unavailable.", file=stderr)
        return 3

    staged = None
    try:
        staged = services.staging_area.stage_file(args.file)
    except (ImportStagingError, OSError):
        print("PDF import failed: source is missing or unsafe.", file=stderr)
        return 2

    try:
        record = services.admission_service.admit_staged(
            context=context,
            request=request,
            staged_path=staged.path,
            staged_evidence=staged.evidence,
        )
    except Exception:
        print("PDF import failed: durable admission is unavailable.", file=stderr)
        return 3
    finally:
        try:
            staged.cleanup()
        except ImportStagingError:
            print("PDF import failed: staging cleanup was unsafe.", file=stderr)
            return 2

    if args.json:
        print(record.model_dump_json(indent=2), file=stdout)
    else:
        print(
            f"RSI Atlas admission: {record.lifecycle.value} ({record.outcome.value})",
            file=stdout,
        )
    return 0


def entrypoint() -> NoReturn:
    raise SystemExit(main())
