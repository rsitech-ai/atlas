import hashlib
import json
import os
import tempfile
from pathlib import Path

from pydantic import ValidationError
from rsi_atlas_contracts import ArtifactDescriptor, ArtifactID, ArtifactIntegrityError


class ContentAddressedArtifactStore:
    def __init__(self, root: Path) -> None:
        self._root = root.resolve()

    def put_bytes(self, payload: bytes, *, media_type: str) -> ArtifactDescriptor:
        digest = hashlib.sha256(payload).hexdigest()
        descriptor = ArtifactDescriptor(
            artifact_id=ArtifactID(f"sha256:{digest}"),
            digest=digest,
            size_bytes=len(payload),
            media_type=media_type,
        )
        directory = self._directory_for(descriptor.artifact_id)
        directory.mkdir(parents=True, exist_ok=True)
        manifest = descriptor.model_dump_json(indent=2).encode("utf-8")
        self._publish_once(directory / "payload", payload)
        self._publish_once(directory / "manifest.json", manifest)
        self._publish_once(
            directory / "manifest.sha256",
            hashlib.sha256(manifest).hexdigest().encode("ascii"),
        )
        return self.verify(descriptor.artifact_id)

    def read_bytes(self, artifact_id: ArtifactID) -> bytes:
        _, payload = self._verified_payload(artifact_id)
        return payload

    def verify(self, artifact_id: ArtifactID) -> ArtifactDescriptor:
        descriptor, _ = self._verified_payload(artifact_id)
        return descriptor

    def payload_path(self, artifact_id: ArtifactID) -> Path:
        return self._directory_for(artifact_id) / "payload"

    def manifest_path(self, artifact_id: ArtifactID) -> Path:
        return self._directory_for(artifact_id) / "manifest.json"

    def _directory_for(self, artifact_id: ArtifactID) -> Path:
        digest = self._digest_from(artifact_id)
        return self._root / "sha256" / digest[:2] / digest[2:4] / digest

    @staticmethod
    def _digest_from(artifact_id: ArtifactID) -> str:
        identifier = str(artifact_id)
        prefix = "sha256:"
        digest = identifier.removeprefix(prefix)
        if not identifier.startswith(prefix) or len(digest) != 64:
            raise ValueError("artifact identifier must be a sha256 lowercase hexadecimal digest")
        if any(character not in "0123456789abcdef" for character in digest):
            raise ValueError("artifact identifier must be a sha256 lowercase hexadecimal digest")
        return digest

    def _verified_payload(self, artifact_id: ArtifactID) -> tuple[ArtifactDescriptor, bytes]:
        descriptor = self._load_descriptor(artifact_id)
        payload = self._read_regular_file(self.payload_path(artifact_id), label="payload")
        actual_digest = hashlib.sha256(payload).hexdigest()
        if actual_digest != descriptor.digest:
            raise ArtifactIntegrityError("artifact content hash mismatch")
        if len(payload) != descriptor.size_bytes:
            raise ArtifactIntegrityError("artifact content size mismatch")
        return descriptor, payload

    def _load_descriptor(self, artifact_id: ArtifactID) -> ArtifactDescriptor:
        manifest = self._read_regular_file(self.manifest_path(artifact_id), label="manifest")
        manifest_hash = self._read_regular_file(
            self._directory_for(artifact_id) / "manifest.sha256", label="manifest hash"
        )
        if manifest_hash != hashlib.sha256(manifest).hexdigest().encode("ascii"):
            raise ArtifactIntegrityError("artifact manifest hash mismatch")
        try:
            descriptor = ArtifactDescriptor.model_validate(json.loads(manifest))
        except (json.JSONDecodeError, ValidationError) as error:
            raise ArtifactIntegrityError("artifact manifest is invalid") from error
        if descriptor.artifact_id != artifact_id:
            raise ArtifactIntegrityError("artifact manifest identifier mismatch")
        return descriptor

    @staticmethod
    def _read_regular_file(path: Path, *, label: str) -> bytes:
        if not path.is_file() or path.is_symlink():
            raise ArtifactIntegrityError(f"artifact {label} is missing")
        try:
            return path.read_bytes()
        except OSError as error:
            raise ArtifactIntegrityError(f"artifact {label} cannot be read") from error

    @staticmethod
    def _publish_once(destination: Path, content: bytes) -> None:
        file_descriptor, staging_name = tempfile.mkstemp(
            prefix=".artifact-", dir=destination.parent
        )
        staging_path = Path(staging_name)
        try:
            with os.fdopen(file_descriptor, "wb") as staging_file:
                staging_file.write(content)
                staging_file.flush()
                os.fsync(staging_file.fileno())
            try:
                os.link(staging_path, destination)
            except FileExistsError as error:
                existing = ContentAddressedArtifactStore._read_regular_file(
                    destination, label="stored file"
                )
                if existing != content:
                    raise ArtifactIntegrityError(
                        "existing immutable artifact file differs"
                    ) from error
        finally:
            staging_path.unlink(missing_ok=True)
