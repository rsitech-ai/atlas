"""Engine-side governed PDF preflight orchestration."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, Protocol
from uuid import UUID, uuid4

from rsi_atlas_contracts import (
    AdmissionOutcome,
    ArtifactCommandContext,
    ArtifactDescriptor,
    DocumentAdmissionRecord,
    SafetyCheckState,
)
from rsi_atlas_contracts.document_parsing import (
    AdmissionAssessmentDraft,
    BoundingBox,
    CoordinateSystem,
    DocumentPreflightProfile,
    DocumentProcessingLifecycle,
    DocumentProfilerIdentity,
    PageGeometry,
)
from rsi_atlas_document_worker.protocol import (
    DocumentWorkerRequest,
    WorkerOperation,
    WorkerResponseStatus,
)
from rsi_atlas_storage.document_processing_repository import (
    AttemptEventKind,
    AttemptOperation,
    DocumentProcessingRepository,
)

from rsi_atlas_ingestion.worker_runner import DocumentWorkerRunner, DocumentWorkerRunnerError

_PROFILER_CONFIG = hashlib.sha256(b"phase-2b-preflight-pypdf-1").hexdigest()


class AdmissionLookup(Protocol):
    def find(
        self, *, context: ArtifactCommandContext, acquisition_id: UUID
    ) -> DocumentAdmissionRecord | None: ...


class PreflightService:
    """Run sandboxed preflight and persist append-only attempt/assessment evidence."""

    def __init__(
        self,
        *,
        admissions: AdmissionLookup,
        processing: DocumentProcessingRepository,
        runner: DocumentWorkerRunner | None = None,
        artifact_path_resolver: Any = None,
    ) -> None:
        self._admissions = admissions
        self._processing = processing
        self._runner = runner or DocumentWorkerRunner()
        self._artifact_path_resolver = artifact_path_resolver

    def run(
        self,
        *,
        context: ArtifactCommandContext,
        acquisition_id: UUID,
        artifact_path: Path,
        run_root: Path,
    ) -> AdmissionAssessmentDraft:
        admission = self._admissions.find(context=context, acquisition_id=acquisition_id)
        if admission is None:
            raise LookupError("acquisition admission record is missing")
        artifact = admission.artifact
        attempt = self._processing.start_attempt(
            context=context,
            acquisition_id=acquisition_id,
            artifact_id=str(artifact.artifact_id),
            operation=AttemptOperation.PREFLIGHT,
            configuration_hash=_PROFILER_CONFIG,
        )
        run_directory = run_root / str(attempt.attempt_id)
        run_directory.mkdir(parents=True, exist_ok=False)
        try:
            result = self._runner.run_request(
                request=_preflight_request(
                    run_id=f"preflight-{attempt.attempt_id}", artifact_path=artifact_path
                ),
                artifact_path=artifact_path,
                run_directory=run_directory,
            )
        except DocumentWorkerRunnerError as error:
            self._processing.finish_attempt(
                context=context,
                attempt_id=attempt.attempt_id,
                event_kind=_map_runner_error(error.code),
                payload={"code": error.code},
            )
            raise

        if result.response.status is not WorkerResponseStatus.SUCCEEDED:
            self._processing.finish_attempt(
                context=context,
                attempt_id=attempt.attempt_id,
                event_kind=AttemptEventKind.FAILED,
                payload={"status": result.response.status.value},
            )
            raise DocumentWorkerRunnerError("worker_preflight_failed")

        evidence_path = run_directory / "preflight.json"
        evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
        profile = _bind_preflight_profile(
            context=context,
            acquisition_id=acquisition_id,
            artifact=artifact,
            evidence=evidence,
        )
        draft = _assessment_from_profile(
            context=context,
            acquisition_id=acquisition_id,
            artifact=artifact,
            prior_admission_hash=_admission_hash(admission),
            profile=profile,
        )
        self._processing.finish_attempt(
            context=context,
            attempt_id=attempt.attempt_id,
            event_kind=AttemptEventKind.SUCCEEDED,
            payload={
                "output_files": list(result.response.output_files),
                "assessment_id": str(draft.assessment_id),
            },
        )
        self._processing.record_assessment(
            context=context,
            assessment_id=draft.assessment_id,
            acquisition_id=acquisition_id,
            attempt_id=attempt.attempt_id,
            artifact_id=str(artifact.artifact_id),
            prior_admission_hash=draft.prior_admission_hash,
            lifecycle=draft.lifecycle.value,
            outcome=draft.outcome.value,
            reason_codes=list(draft.reason_codes),
            assessment=json.loads(draft.model_dump_json()),
        )
        return draft


def _preflight_request(*, run_id: str, artifact_path: Path) -> DocumentWorkerRequest:
    payload = artifact_path.read_bytes()
    return DocumentWorkerRequest(
        operation=WorkerOperation.PREFLIGHT,
        run_id=run_id,
        artifact_sha256=hashlib.sha256(payload).hexdigest(),
        artifact_size_bytes=len(payload),
    )


def _map_runner_error(code: str) -> AttemptEventKind:
    if code == "worker_timeout":
        return AttemptEventKind.TIMED_OUT
    return AttemptEventKind.FAILED


def _admission_hash(record: DocumentAdmissionRecord) -> str:
    return hashlib.sha256(record.model_dump_json().encode()).hexdigest()


def _bind_preflight_profile(
    *,
    context: ArtifactCommandContext,
    acquisition_id: UUID,
    artifact: ArtifactDescriptor,
    evidence: dict[str, Any],
) -> DocumentPreflightProfile:
    pages = tuple(
        PageGeometry(
            page_number=page["page_number"],
            media_box=BoundingBox(
                coordinate_system=CoordinateSystem.PDF_BOTTOM_LEFT_POINTS,
                left=Decimal(page["media_box"]["left"]),
                top=Decimal(page["media_box"]["top"]),
                right=Decimal(page["media_box"]["right"]),
                bottom=Decimal(page["media_box"]["bottom"]),
            ),
            crop_box=BoundingBox(
                coordinate_system=CoordinateSystem.PDF_BOTTOM_LEFT_POINTS,
                left=Decimal(page["crop_box"]["left"]),
                top=Decimal(page["crop_box"]["top"]),
                right=Decimal(page["crop_box"]["right"]),
                bottom=Decimal(page["crop_box"]["bottom"]),
            ),
            rotation_degrees=page["rotation_degrees"],
        )
        for page in evidence.get("pages", [])
    )
    profiler = DocumentProfilerIdentity(
        profiler_id="pypdf_preflight",
        name="pypdf",
        version="6.14.2",
        build_hash=hashlib.sha256(b"pypdf==6.14.2").hexdigest(),
        configuration_hash=_PROFILER_CONFIG,
    )
    return DocumentPreflightProfile(
        preflight_run_id=uuid4(),
        context=context,
        acquisition_id=acquisition_id,
        artifact=artifact,
        profiler=profiler,
        page_count=evidence.get("page_count"),
        pages=pages,
        encryption_password_state=SafetyCheckState(evidence["encryption_password_state"]),
        malformed_structure=SafetyCheckState(evidence["malformed_structure"]),
        embedded_files=SafetyCheckState(evidence["embedded_files"]),
        active_actions=SafetyCheckState(evidence["active_actions"]),
        suspicious_references=SafetyCheckState(evidence["suspicious_references"]),
        decompression_ratio=SafetyCheckState(evidence["decompression_ratio"]),
        decoded_stream_bytes=int(evidence["decoded_stream_bytes"]),
        character_count=int(evidence["character_count"]),
        image_only_page_count=evidence.get("image_only_page_count"),
        warnings=tuple(evidence.get("warnings", ())),
        profiled_at=datetime.now(UTC),
    )


def _assessment_from_profile(
    *,
    context: ArtifactCommandContext,
    acquisition_id: UUID,
    artifact: ArtifactDescriptor,
    prior_admission_hash: str,
    profile: DocumentPreflightProfile,
) -> AdmissionAssessmentDraft:
    # Without an explicit promotion record, never emit accept outcomes.
    if profile.encryption_password_state is SafetyCheckState.FAIL:
        outcome = AdmissionOutcome.REQUEST_PASSWORD
        lifecycle = DocumentProcessingLifecycle.AWAITING_PASSWORD
        reasons = ("password_required_or_encrypted",)
    elif profile.malformed_structure is SafetyCheckState.FAIL:
        outcome = AdmissionOutcome.REJECT_UNSAFE
        lifecycle = DocumentProcessingLifecycle.FAILED_TERMINAL
        reasons = ("malformed_or_unreadable_pdf",)
    elif profile.active_actions is SafetyCheckState.FAIL:
        outcome = AdmissionOutcome.REJECT_UNSAFE
        lifecycle = DocumentProcessingLifecycle.FAILED_TERMINAL
        reasons = ("active_actions_present",)
    elif profile.embedded_files is SafetyCheckState.FAIL:
        outcome = AdmissionOutcome.QUARANTINE_FOR_REVIEW
        lifecycle = DocumentProcessingLifecycle.AWAITING_REVIEW
        reasons = ("embedded_files_present",)
    else:
        outcome = AdmissionOutcome.QUARANTINE_FOR_REVIEW
        lifecycle = DocumentProcessingLifecycle.AWAITING_REVIEW
        reasons = ("promotion_required_before_accept",)
    return AdmissionAssessmentDraft(
        assessment_id=uuid4(),
        context=context,
        acquisition_id=acquisition_id,
        artifact=artifact,
        prior_admission_hash=prior_admission_hash,
        preflight=profile,
        promotion=None,
        lifecycle=lifecycle,
        outcome=outcome,
        reason_codes=reasons,
        assessed_at=datetime.now(UTC),
    )
