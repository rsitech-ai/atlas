"""Acquisition-bound Tier-0 parser orchestration with attempt journal persistence."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Protocol
from uuid import UUID

from rsi_atlas_contracts import ArtifactCommandContext, DocumentAdmissionRecord
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

from rsi_atlas_ingestion.parser_benchmark import QUALIFICATION_PATH, qualify_development_candidate
from rsi_atlas_ingestion.worker_runner import DocumentWorkerRunner, DocumentWorkerRunnerError

_PARSER_CONFIG = hashlib.sha256(b"phase-2b-parse-pypdf-1").hexdigest()
_QUALIFIED_CANDIDATE = "pypdf"


class AdmissionLookup(Protocol):
    def find(
        self, *, context: ArtifactCommandContext, acquisition_id: UUID
    ) -> DocumentAdmissionRecord | None: ...


class ParserService:
    """Run the development-qualified Tier-0 parser under Seatbelt with attempt history."""

    def __init__(
        self,
        *,
        admissions: AdmissionLookup,
        processing: DocumentProcessingRepository,
        runner: DocumentWorkerRunner | None = None,
    ) -> None:
        self._admissions = admissions
        self._processing = processing
        self._runner = runner or DocumentWorkerRunner()

    def run(
        self,
        *,
        context: ArtifactCommandContext,
        acquisition_id: UUID,
        artifact_path: Path,
        run_root: Path,
    ) -> dict[str, Any]:
        admission = self._admissions.find(context=context, acquisition_id=acquisition_id)
        if admission is None:
            raise LookupError("acquisition admission record is missing")
        qualification = (
            json.loads(QUALIFICATION_PATH.read_text(encoding="utf-8"))
            if QUALIFICATION_PATH.is_file()
            else qualify_development_candidate()
        )
        qualified = qualification.get("qualified_development_candidate")
        if qualified is None or qualified.get("candidate") != _QUALIFIED_CANDIDATE:
            raise DocumentWorkerRunnerError("parser_unqualified")

        attempt = self._processing.start_attempt(
            context=context,
            acquisition_id=acquisition_id,
            artifact_id=str(admission.artifact.artifact_id),
            operation=AttemptOperation.PARSE,
            configuration_hash=_PARSER_CONFIG,
        )
        run_directory = run_root / str(attempt.attempt_id)
        run_directory.mkdir(parents=True, exist_ok=False)
        payload = artifact_path.read_bytes()
        request = DocumentWorkerRequest(
            operation=WorkerOperation.PARSE,
            run_id=f"parse-{attempt.attempt_id}",
            artifact_sha256=hashlib.sha256(payload).hexdigest(),
            artifact_size_bytes=len(payload),
        )
        try:
            result = self._runner.run_request(
                request=request,
                artifact_path=artifact_path,
                run_directory=run_directory,
            )
        except DocumentWorkerRunnerError as error:
            kind = (
                AttemptEventKind.TIMED_OUT
                if error.code == "worker_timeout"
                else AttemptEventKind.FAILED
            )
            self._processing.finish_attempt(
                context=context,
                attempt_id=attempt.attempt_id,
                event_kind=kind,
                payload={"code": error.code},
            )
            raise

        output_path = run_directory / "parse_result.json"
        parse_result = json.loads(output_path.read_text(encoding="utf-8"))
        output_hash = hashlib.sha256(output_path.read_bytes()).hexdigest()
        if result.response.status is not WorkerResponseStatus.SUCCEEDED:
            self._processing.finish_attempt(
                context=context,
                attempt_id=attempt.attempt_id,
                event_kind=AttemptEventKind.FAILED,
                payload={"status": result.response.status.value, "output_hash": output_hash},
            )
            raise DocumentWorkerRunnerError("worker_parse_failed")

        self._processing.finish_attempt(
            context=context,
            attempt_id=attempt.attempt_id,
            event_kind=AttemptEventKind.SUCCEEDED,
            payload={
                "output_hash": output_hash,
                "candidate": _QUALIFIED_CANDIDATE,
                "warnings": parse_result.get("warnings") or [],
            },
        )
        return {
            "attempt_id": str(attempt.attempt_id),
            "output_hash": output_hash,
            "parse_result": parse_result,
            "qualified_candidate": qualified,
        }
