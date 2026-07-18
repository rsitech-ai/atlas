import hashlib
import os
import stat
import threading

from rsi_atlas_contracts.models import ModelArtifact, ModelLifecycle


class ModelRegistryError(RuntimeError):
    pass


_TRANSITIONS = {
    ModelLifecycle.IMPORTED: {ModelLifecycle.VALIDATED, ModelLifecycle.RETIRED},
    ModelLifecycle.VALIDATED: {ModelLifecycle.RETIRED},
    ModelLifecycle.RETIRED: set(),
}


class ModelRegistry:
    def __init__(self, *, max_bytes: int = 64 * 1024 * 1024 * 1024) -> None:
        self._lock = threading.RLock()
        self._by_id: dict[object, ModelArtifact] = {}
        self._hashes: set[str] = set()
        self._max_bytes = max_bytes

    def register(self, artifact: ModelArtifact) -> ModelArtifact:
        with self._lock:
            if artifact.artifact_id in self._by_id or artifact.sha256 in self._hashes:
                raise ModelRegistryError("duplicate model artifact")
            self._validate_file(artifact)
            self._by_id[artifact.artifact_id] = artifact
            self._hashes.add(artifact.sha256)
            return artifact

    def get(self, artifact_id: object) -> ModelArtifact:
        with self._lock:
            try:
                return self._by_id[artifact_id]
            except KeyError as error:
                raise ModelRegistryError("model artifact not found") from error

    def transition(self, artifact_id: object, lifecycle: ModelLifecycle) -> ModelArtifact:
        with self._lock:
            prior = self.get(artifact_id)
            if lifecycle not in _TRANSITIONS[prior.lifecycle]:
                raise ModelRegistryError("invalid model lifecycle transition")
            current = prior.model_copy(update={"lifecycle": lifecycle})
            self._by_id[artifact_id] = current
            return current

    def _validate_file(self, artifact: ModelArtifact) -> None:
        fd = os.open(artifact.local_path, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
        try:
            info = os.fstat(fd)
            if (
                not stat.S_ISREG(info.st_mode)
                or info.st_nlink != 1
                or info.st_uid != os.getuid()
                or stat.S_IMODE(info.st_mode) & 0o022
                or info.st_size > self._max_bytes
            ):
                raise ModelRegistryError("model artifact file is unsafe")
            digest = hashlib.sha256()
            while block := os.read(fd, 1024 * 1024):
                digest.update(block)
            if digest.hexdigest() != artifact.sha256:
                raise ModelRegistryError("model artifact hash mismatch")
        except OSError as error:
            raise ModelRegistryError("model artifact file is unavailable") from error
        finally:
            os.close(fd)
