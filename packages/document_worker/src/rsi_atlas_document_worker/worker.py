"""Document-worker entrypoint. Task 4 ships echo_hash only; PDF libraries stay out."""

from __future__ import annotations

import hashlib
import os
import sys

from rsi_atlas_document_worker.protocol import (
    DocumentWorkerRequest,
    DocumentWorkerResponse,
    WorkerFailureCode,
    WorkerOperation,
    WorkerResponseStatus,
    decode_request,
    encode_response,
    worker_identity,
)

ARTIFACT_FD = 3
RUN_DIRECTORY_FD = 4
_READ_CHUNK = 1024 * 1024


def _fail(
    request: DocumentWorkerRequest | None,
    *,
    code: WorkerFailureCode,
    artifact_sha256: str = "0" * 64,
    artifact_size_bytes: int = 0,
) -> DocumentWorkerResponse:
    return DocumentWorkerResponse(
        operation=request.operation if request is not None else WorkerOperation.ECHO_HASH,
        run_id=request.run_id if request is not None else "invalid-request",
        status=WorkerResponseStatus.FAILED,
        artifact_sha256=artifact_sha256,
        artifact_size_bytes=artifact_size_bytes,
        worker=worker_identity(),
        failure_code=code,
        output_files=(),
    )


def _hash_artifact_fd(descriptor: int, expected_size: int) -> tuple[str, int]:
    digest = hashlib.sha256()
    total = 0
    while True:
        chunk = os.read(descriptor, _READ_CHUNK)
        if not chunk:
            break
        total += len(chunk)
        if total > expected_size:
            raise ValueError("artifact larger than declared size")
        digest.update(chunk)
    return digest.hexdigest(), total


def _write_run_file(run_dir_fd: int, name: str, payload: bytes, max_output_bytes: int) -> None:
    if len(payload) > max_output_bytes:
        raise ValueError("output exceeds bounded size")
    if "/" in name or name in {".", ".."} or not name:
        raise ValueError("unsafe output name")
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_CLOEXEC", 0)
    out_fd = os.open(name, flags, 0o600, dir_fd=run_dir_fd)
    try:
        written = 0
        while written < len(payload):
            written += os.write(out_fd, payload[written:])
    finally:
        os.close(out_fd)


def handle_request(request: DocumentWorkerRequest) -> DocumentWorkerResponse:
    # Task 4 only ships echo_hash; future operations extend WorkerOperation first.
    try:
        digest, size = _hash_artifact_fd(ARTIFACT_FD, request.artifact_size_bytes)
    except (OSError, ValueError):
        return _fail(request, code=WorkerFailureCode.ARTIFACT_MISMATCH)

    if digest != request.artifact_sha256 or size != request.artifact_size_bytes:
        return _fail(
            request,
            code=WorkerFailureCode.ARTIFACT_MISMATCH,
            artifact_sha256=digest,
            artifact_size_bytes=size,
        )

    evidence = (
        '{"artifact_sha256":"'
        + digest
        + '","artifact_size_bytes":'
        + str(size)
        + ',"run_id":"'
        + request.run_id
        + '"}\n'
    ).encode()
    try:
        _write_run_file(RUN_DIRECTORY_FD, "echo_hash.json", evidence, request.max_output_bytes)
    except (OSError, ValueError):
        return _fail(
            request,
            code=WorkerFailureCode.OUTPUT_LIMIT,
            artifact_sha256=digest,
            artifact_size_bytes=size,
        )

    return DocumentWorkerResponse(
        operation=WorkerOperation.ECHO_HASH,
        run_id=request.run_id,
        status=WorkerResponseStatus.SUCCEEDED,
        artifact_sha256=digest,
        artifact_size_bytes=size,
        worker=worker_identity(),
        failure_code=None,
        output_files=("echo_hash.json",),
    )


def main(argv: list[str] | None = None) -> int:
    del argv  # argv is unused; FDs and stdin carry the contract
    request: DocumentWorkerRequest | None = None
    try:
        payload = sys.stdin.buffer.read()
        request = decode_request(payload)
        response = handle_request(request)
    except Exception:
        response = _fail(request, code=WorkerFailureCode.INTERNAL)
    sys.stdout.buffer.write(encode_response(response))
    sys.stdout.buffer.flush()
    return 0 if response.status is WorkerResponseStatus.SUCCEEDED else 1


if __name__ == "__main__":
    raise SystemExit(main())
