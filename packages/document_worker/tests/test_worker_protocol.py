from __future__ import annotations

import os

import pytest
from pydantic import ValidationError
from rsi_atlas_document_worker.protocol import (
    WORKER_BUILD_HASH,
    DocumentWorkerRequest,
    DocumentWorkerResponse,
    WorkerFailureCode,
    WorkerOperation,
    WorkerResponseStatus,
    decode_request,
    decode_response,
    encode_request,
    encode_response,
    worker_identity,
)
from rsi_atlas_document_worker.worker import handle_request


def test_request_and_response_round_trip_is_strict() -> None:
    request = DocumentWorkerRequest(
        operation=WorkerOperation.ECHO_HASH,
        run_id="run-echo-001",
        artifact_sha256="a" * 64,
        artifact_size_bytes=12,
    )
    encoded = encode_request(request)
    assert decode_request(encoded) == request

    response = DocumentWorkerResponse(
        operation=WorkerOperation.ECHO_HASH,
        run_id="run-echo-001",
        status=WorkerResponseStatus.SUCCEEDED,
        artifact_sha256="a" * 64,
        artifact_size_bytes=12,
        worker=worker_identity(),
        output_files=("echo_hash.json",),
    )
    assert decode_response(encode_response(response)) == response
    assert response.worker.build_hash == WORKER_BUILD_HASH


def test_protocol_rejects_unknown_fields_and_unsafe_outputs() -> None:
    with pytest.raises(ValidationError):
        DocumentWorkerRequest.model_validate(
            {
                "schema_version": "rsi-atlas.document-worker.request.v1",
                "operation": "echo_hash",
                "run_id": "run-echo-001",
                "artifact_sha256": "a" * 64,
                "artifact_size_bytes": 1,
                "extra": True,
            }
        )
    with pytest.raises(ValidationError):
        DocumentWorkerResponse.model_validate(
            {
                "schema_version": "rsi-atlas.document-worker.response.v1",
                "operation": "echo_hash",
                "run_id": "run-echo-001",
                "status": "succeeded",
                "artifact_sha256": "a" * 64,
                "artifact_size_bytes": 1,
                "worker": worker_identity().model_dump(),
                "output_files": ["../escape.json"],
            }
        )


def test_handle_request_rejects_missing_artifact_descriptor(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request = DocumentWorkerRequest(
        operation=WorkerOperation.ECHO_HASH,
        run_id="run-echo-002",
        artifact_sha256="b" * 64,
        artifact_size_bytes=0,
    )

    def missing_artifact_fd(descriptor: int, size: int) -> bytes:
        del size
        assert descriptor == 3
        raise OSError("artifact descriptor is not open")

    # Explicitly simulate the worker contract's missing FD 3. The test runner may itself inherit an
    # unrelated descriptor 3, so relying on ambient process descriptors can block the test.
    monkeypatch.setattr(os, "read", missing_artifact_fd)
    response = handle_request(request)
    assert response.status is WorkerResponseStatus.FAILED
    assert response.failure_code is WorkerFailureCode.ARTIFACT_MISMATCH
