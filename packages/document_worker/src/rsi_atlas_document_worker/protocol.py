"""Strict request/response contract for the isolated document worker."""

from __future__ import annotations

from enum import StrEnum
from hashlib import sha256
from typing import Literal

from pydantic import Field, field_validator
from rsi_atlas_contracts.system_status import StrictModel

REQUEST_SCHEMA: Literal["rsi-atlas.document-worker.request.v1"] = (
    "rsi-atlas.document-worker.request.v1"
)
RESPONSE_SCHEMA: Literal["rsi-atlas.document-worker.response.v1"] = (
    "rsi-atlas.document-worker.response.v1"
)
WORKER_NAME: Literal["rsi-atlas-document-worker"] = "rsi-atlas-document-worker"
WORKER_VERSION: Literal["0.1.0"] = "0.1.0"
WORKER_CAPABILITIES = frozenset({"echo_hash"})
_SHA256 = r"^[0-9a-f]{64}$"
_MAX_REQUEST_BYTES = 64 * 1024
_MAX_RESPONSE_BYTES = 256 * 1024


def _worker_build_hash() -> str:
    payload = f"{WORKER_NAME}:{WORKER_VERSION}:{','.join(sorted(WORKER_CAPABILITIES))}".encode()
    return sha256(payload).hexdigest()


WORKER_BUILD_HASH = _worker_build_hash()


class WorkerOperation(StrEnum):
    ECHO_HASH = "echo_hash"


class WorkerResponseStatus(StrEnum):
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class WorkerFailureCode(StrEnum):
    INVALID_REQUEST = "invalid_request"
    ARTIFACT_MISMATCH = "artifact_mismatch"
    OUTPUT_LIMIT = "output_limit"
    INTERNAL = "internal"


class DocumentWorkerIdentity(StrictModel):
    name: Literal["rsi-atlas-document-worker"] = WORKER_NAME
    version: Literal["0.1.0"] = WORKER_VERSION
    build_hash: str = Field(pattern=_SHA256)
    capabilities: tuple[str, ...] = Field(min_length=1, max_length=16)

    @field_validator("capabilities")
    @classmethod
    def capabilities_are_sorted_unique(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if list(value) != sorted(set(value)):
            raise ValueError("capabilities must be sorted unique identifiers")
        return value


class DocumentWorkerRequest(StrictModel):
    schema_version: Literal["rsi-atlas.document-worker.request.v1"] = REQUEST_SCHEMA
    operation: WorkerOperation
    run_id: str = Field(min_length=8, max_length=128, pattern=r"^[A-Za-z0-9._:-]+$")
    artifact_sha256: str = Field(pattern=_SHA256)
    artifact_size_bytes: int = Field(ge=0, le=100_000_000)
    artifact_fd: Literal[3] = 3
    run_directory_fd: Literal[4] = 4
    max_output_bytes: int = Field(ge=1, le=50_000_000, default=1_048_576)


class DocumentWorkerResponse(StrictModel):
    schema_version: Literal["rsi-atlas.document-worker.response.v1"] = RESPONSE_SCHEMA
    operation: WorkerOperation
    run_id: str = Field(min_length=8, max_length=128, pattern=r"^[A-Za-z0-9._:-]+$")
    status: WorkerResponseStatus
    artifact_sha256: str = Field(pattern=_SHA256)
    artifact_size_bytes: int = Field(ge=0, le=100_000_000)
    worker: DocumentWorkerIdentity
    failure_code: WorkerFailureCode | None = None
    output_files: tuple[str, ...] = ()

    @field_validator("output_files")
    @classmethod
    def output_files_are_safe_names(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        for name in value:
            if not name or "/" in name or "\\" in name or name in {".", ".."}:
                raise ValueError("output file names must be basename-only")
        if list(value) != sorted(set(value)):
            raise ValueError("output_files must be sorted unique basenames")
        return value


def encode_request(request: DocumentWorkerRequest) -> bytes:
    payload = request.model_dump_json().encode("utf-8")
    if len(payload) > _MAX_REQUEST_BYTES:
        raise ValueError("request exceeds bounded size")
    return payload


def decode_request(payload: bytes) -> DocumentWorkerRequest:
    if len(payload) > _MAX_REQUEST_BYTES:
        raise ValueError("request exceeds bounded size")
    return DocumentWorkerRequest.model_validate_json(payload)


def encode_response(response: DocumentWorkerResponse) -> bytes:
    payload = response.model_dump_json().encode("utf-8")
    if len(payload) > _MAX_RESPONSE_BYTES:
        raise ValueError("response exceeds bounded size")
    return payload


def decode_response(payload: bytes) -> DocumentWorkerResponse:
    if len(payload) > _MAX_RESPONSE_BYTES:
        raise ValueError("response exceeds bounded size")
    return DocumentWorkerResponse.model_validate_json(payload)


def worker_identity() -> DocumentWorkerIdentity:
    return DocumentWorkerIdentity(
        build_hash=WORKER_BUILD_HASH,
        capabilities=tuple(sorted(WORKER_CAPABILITIES)),
    )
