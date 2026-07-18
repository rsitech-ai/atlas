from __future__ import annotations

import hashlib
import os
import stat
import threading
from enum import StrEnum
from pathlib import Path
from uuid import UUID

from rsi_atlas_contracts.models import ModelArtifact, ModelLifecycle

_HASH_CHUNK_BYTES = 1024 * 1024
_DEFAULT_MAX_BYTES = 64 * 1024 * 1024 * 1024
_MAX_CONFIGURED_BYTES = 1024 * 1024 * 1024 * 1024
_DIRECTORY_FLAGS = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
_FILE_FLAGS = os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW | os.O_CLOEXEC


class ModelRegistryErrorCode(StrEnum):
    INVALID_REGISTRY_LIMIT = "invalid_registry_limit"
    INVALID_ARTIFACT = "invalid_artifact"
    INVALID_ARTIFACT_ID = "invalid_artifact_id"
    INVALID_INITIAL_LIFECYCLE = "invalid_initial_lifecycle"
    INVALID_LIFECYCLE = "invalid_lifecycle"
    INVALID_LIFECYCLE_TRANSITION = "invalid_lifecycle_transition"
    PROMOTION_EVIDENCE_MISSING = "promotion_evidence_missing"
    DUPLICATE_ARTIFACT_ID = "duplicate_artifact_id"
    DUPLICATE_ARTIFACT_HASH = "duplicate_artifact_hash"
    ARTIFACT_NOT_FOUND = "artifact_not_found"
    ARTIFACT_UNAVAILABLE = "artifact_unavailable"
    UNSAFE_ARTIFACT_PATH = "unsafe_artifact_path"
    UNSAFE_ARTIFACT_FILE = "unsafe_artifact_file"
    ARTIFACT_TOO_LARGE = "artifact_too_large"
    ARTIFACT_HASH_MISMATCH = "artifact_hash_mismatch"
    ARTIFACT_IDENTITY_CHANGED = "artifact_identity_changed"


class ModelRegistryError(RuntimeError):
    def __init__(self, code: ModelRegistryErrorCode) -> None:
        self.code = code
        super().__init__(code.value)


_TRANSITIONS: dict[ModelLifecycle, frozenset[ModelLifecycle]] = {
    ModelLifecycle.IMPORTED: frozenset({ModelLifecycle.QUARANTINED, ModelLifecycle.RETIRED}),
    ModelLifecycle.QUARANTINED: frozenset({ModelLifecycle.BENCHMARKING, ModelLifecycle.REJECTED}),
    ModelLifecycle.BENCHMARKING: frozenset({ModelLifecycle.CANDIDATE, ModelLifecycle.REJECTED}),
    ModelLifecycle.CANDIDATE: frozenset({ModelLifecycle.PRODUCTION, ModelLifecycle.REJECTED}),
    ModelLifecycle.PRODUCTION: frozenset({ModelLifecycle.DEGRADED, ModelLifecycle.DEPRECATED}),
    ModelLifecycle.DEGRADED: frozenset({ModelLifecycle.PRODUCTION, ModelLifecycle.DEPRECATED}),
    ModelLifecycle.DEPRECATED: frozenset({ModelLifecycle.RETIRED}),
    ModelLifecycle.RETIRED: frozenset(),
    ModelLifecycle.REJECTED: frozenset(),
}


def _identity(metadata: os.stat_result) -> tuple[int, int]:
    return (metadata.st_dev, metadata.st_ino)


def _file_snapshot(metadata: os.stat_result) -> tuple[int, int, int, int, int, int, int]:
    return (
        metadata.st_dev,
        metadata.st_ino,
        metadata.st_size,
        metadata.st_mode,
        metadata.st_uid,
        metadata.st_nlink,
        metadata.st_ctime_ns,
    )


class ModelRegistry:
    def __init__(self, *, max_bytes: int = _DEFAULT_MAX_BYTES) -> None:
        if type(max_bytes) is not int or max_bytes <= 0 or max_bytes > _MAX_CONFIGURED_BYTES:
            raise ModelRegistryError(ModelRegistryErrorCode.INVALID_REGISTRY_LIMIT)
        self._lock = threading.RLock()
        self._by_id: dict[UUID, ModelArtifact] = {}
        self._by_hash: dict[str, UUID] = {}
        self._history: dict[UUID, tuple[ModelArtifact, ...]] = {}
        self._max_bytes = max_bytes

    def register(self, artifact: ModelArtifact) -> ModelArtifact:
        if type(artifact) is not ModelArtifact:
            raise ModelRegistryError(ModelRegistryErrorCode.INVALID_ARTIFACT)
        with self._lock:
            if artifact.artifact_id in self._by_id:
                raise ModelRegistryError(ModelRegistryErrorCode.DUPLICATE_ARTIFACT_ID)
            if artifact.sha256 in self._by_hash:
                raise ModelRegistryError(ModelRegistryErrorCode.DUPLICATE_ARTIFACT_HASH)
            if artifact.lifecycle is not ModelLifecycle.IMPORTED:
                raise ModelRegistryError(ModelRegistryErrorCode.INVALID_INITIAL_LIFECYCLE)
            self._validate_file(artifact)
            self._by_id[artifact.artifact_id] = artifact
            self._by_hash[artifact.sha256] = artifact.artifact_id
            self._history[artifact.artifact_id] = (artifact,)
            return artifact

    def get(self, artifact_id: UUID) -> ModelArtifact:
        identifier = self._require_artifact_id(artifact_id)
        with self._lock:
            try:
                return self._by_id[identifier]
            except KeyError as error:
                raise ModelRegistryError(ModelRegistryErrorCode.ARTIFACT_NOT_FOUND) from error

    def transition(self, artifact_id: UUID, lifecycle: ModelLifecycle) -> ModelArtifact:
        identifier = self._require_artifact_id(artifact_id)
        if type(lifecycle) is not ModelLifecycle:
            raise ModelRegistryError(ModelRegistryErrorCode.INVALID_LIFECYCLE)
        with self._lock:
            try:
                prior = self._by_id[identifier]
            except KeyError as error:
                raise ModelRegistryError(ModelRegistryErrorCode.ARTIFACT_NOT_FOUND) from error
            if lifecycle not in _TRANSITIONS[prior.lifecycle]:
                raise ModelRegistryError(ModelRegistryErrorCode.INVALID_LIFECYCLE_TRANSITION)
            if lifecycle is ModelLifecycle.PRODUCTION:
                if (
                    not prior.capabilities
                    or not prior.capability_results
                    or not prior.approved_tasks
                ):
                    raise ModelRegistryError(ModelRegistryErrorCode.PROMOTION_EVIDENCE_MISSING)
                self._validate_file(prior)
            current = prior.model_copy(update={"lifecycle": lifecycle})
            self._by_id[identifier] = current
            self._history[identifier] = (*self._history[identifier], current)
            return current

    def history(self, artifact_id: UUID) -> tuple[ModelArtifact, ...]:
        identifier = self._require_artifact_id(artifact_id)
        with self._lock:
            try:
                return self._history[identifier]
            except KeyError as error:
                raise ModelRegistryError(ModelRegistryErrorCode.ARTIFACT_NOT_FOUND) from error

    def snapshot(self) -> tuple[ModelArtifact, ...]:
        with self._lock:
            return tuple(
                sorted(
                    self._by_id.values(),
                    key=lambda artifact: artifact.artifact_id.int,
                )
            )

    @staticmethod
    def _require_artifact_id(artifact_id: UUID) -> UUID:
        if type(artifact_id) is not UUID or artifact_id.int == 0:
            raise ModelRegistryError(ModelRegistryErrorCode.INVALID_ARTIFACT_ID)
        return artifact_id

    def _validate_file(self, artifact: ModelArtifact) -> None:
        parent_fd = -1
        file_fd = -1
        try:
            parent_fd, parent_identity = self._open_parent(artifact.local_path.parent)
            try:
                file_fd = os.open(
                    artifact.local_path.name,
                    _FILE_FLAGS,
                    dir_fd=parent_fd,
                )
            except FileNotFoundError as error:
                raise ModelRegistryError(ModelRegistryErrorCode.ARTIFACT_UNAVAILABLE) from error
            except OSError as error:
                raise ModelRegistryError(ModelRegistryErrorCode.UNSAFE_ARTIFACT_PATH) from error
            before = os.fstat(file_fd)
            self._require_safe_file(before)
            before_snapshot = _file_snapshot(before)
            digest = self._hash_descriptor(file_fd)
            after = os.fstat(file_fd)
            self._require_safe_file(after)
            if _file_snapshot(after) != before_snapshot:
                raise ModelRegistryError(ModelRegistryErrorCode.ARTIFACT_IDENTITY_CHANGED)
            try:
                path_metadata = os.stat(
                    artifact.local_path.name,
                    dir_fd=parent_fd,
                    follow_symlinks=False,
                )
            except OSError as error:
                raise ModelRegistryError(
                    ModelRegistryErrorCode.ARTIFACT_IDENTITY_CHANGED
                ) from error
            self._require_safe_file(path_metadata)
            if _identity(path_metadata) != _identity(after):
                raise ModelRegistryError(ModelRegistryErrorCode.ARTIFACT_IDENTITY_CHANGED)
            fresh_parent_fd, fresh_parent_identity = self._open_parent(artifact.local_path.parent)
            os.close(fresh_parent_fd)
            if fresh_parent_identity != parent_identity:
                raise ModelRegistryError(ModelRegistryErrorCode.ARTIFACT_IDENTITY_CHANGED)
            if digest != artifact.sha256:
                raise ModelRegistryError(ModelRegistryErrorCode.ARTIFACT_HASH_MISMATCH)
        except ModelRegistryError:
            raise
        except FileNotFoundError as error:
            raise ModelRegistryError(ModelRegistryErrorCode.ARTIFACT_UNAVAILABLE) from error
        except OSError as error:
            raise ModelRegistryError(ModelRegistryErrorCode.UNSAFE_ARTIFACT_PATH) from error
        finally:
            if file_fd >= 0:
                os.close(file_fd)
            if parent_fd >= 0:
                os.close(parent_fd)

    def _open_parent(self, path: Path) -> tuple[int, tuple[int, int]]:
        if not path.is_absolute() or path != Path(os.path.normpath(path)):
            raise ModelRegistryError(ModelRegistryErrorCode.UNSAFE_ARTIFACT_PATH)
        descriptor = -1
        try:
            descriptor = os.open(os.sep, _DIRECTORY_FLAGS)
            for component in path.parts[1:]:
                next_descriptor = os.open(component, _DIRECTORY_FLAGS, dir_fd=descriptor)
                os.close(descriptor)
                descriptor = next_descriptor
                self._require_safe_directory(os.fstat(descriptor))
            metadata = os.fstat(descriptor)
            return descriptor, _identity(metadata)
        except ModelRegistryError:
            if descriptor >= 0:
                os.close(descriptor)
            raise
        except OSError as error:
            if descriptor >= 0:
                os.close(descriptor)
            raise ModelRegistryError(ModelRegistryErrorCode.UNSAFE_ARTIFACT_PATH) from error

    @staticmethod
    def _require_safe_directory(metadata: os.stat_result) -> None:
        if (
            not stat.S_ISDIR(metadata.st_mode)
            or metadata.st_uid not in {0, os.getuid()}
            or stat.S_IMODE(metadata.st_mode) & 0o022
        ):
            raise ModelRegistryError(ModelRegistryErrorCode.UNSAFE_ARTIFACT_PATH)

    def _require_safe_file(self, metadata: os.stat_result) -> None:
        if (
            not stat.S_ISREG(metadata.st_mode)
            or metadata.st_nlink != 1
            or metadata.st_uid != os.getuid()
            or stat.S_IMODE(metadata.st_mode) & 0o022
        ):
            raise ModelRegistryError(ModelRegistryErrorCode.UNSAFE_ARTIFACT_FILE)
        if metadata.st_size > self._max_bytes:
            raise ModelRegistryError(ModelRegistryErrorCode.ARTIFACT_TOO_LARGE)

    def _hash_descriptor(self, descriptor: int) -> str:
        digest = hashlib.sha256()
        total = 0
        os.lseek(descriptor, 0, os.SEEK_SET)
        while block := os.read(descriptor, _HASH_CHUNK_BYTES):
            total += len(block)
            if total > self._max_bytes:
                raise ModelRegistryError(ModelRegistryErrorCode.ARTIFACT_TOO_LARGE)
            digest.update(block)
        return digest.hexdigest()


__all__ = [
    "ModelRegistry",
    "ModelRegistryError",
    "ModelRegistryErrorCode",
]
