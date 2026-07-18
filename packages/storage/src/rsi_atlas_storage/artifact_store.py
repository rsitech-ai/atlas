import hashlib
import json
import os
import tempfile
from pathlib import Path

from pydantic import ValidationError
from rsi_atlas_contracts import (
    ArtifactCommandContext,
    ArtifactDescriptor,
    ArtifactID,
    ArtifactIntegrityError,
)


class ContentAddressedArtifactStore:
    def __init__(self, root: Path) -> None:
        self._root = root.absolute()

    def put_bytes(
        self,
        payload: bytes,
        *,
        media_type: str,
        context: ArtifactCommandContext,
    ) -> ArtifactDescriptor:
        context = self._require_context(context)
        digest = hashlib.sha256(payload).hexdigest()
        descriptor = ArtifactDescriptor(
            artifact_id=ArtifactID(f"sha256:{digest}"),
            digest=digest,
            size_bytes=len(payload),
            media_type=media_type,
        )
        directory = self._prepare_artifact_directory(descriptor.artifact_id)
        manifest = descriptor.model_dump_json(indent=2).encode("utf-8")
        self._publish_once(directory / "payload", payload)
        self._publish_once(directory / "manifest.json", manifest)
        self._publish_once(
            directory / "manifest.sha256",
            hashlib.sha256(manifest).hexdigest().encode("ascii"),
        )
        return self.verify(descriptor.artifact_id, context=context)

    def read_bytes(self, artifact_id: ArtifactID, *, context: ArtifactCommandContext) -> bytes:
        self._require_context(context)
        _, payload = self._verified_payload(artifact_id)
        return payload

    def verify(
        self, artifact_id: ArtifactID, *, context: ArtifactCommandContext
    ) -> ArtifactDescriptor:
        self._require_context(context)
        descriptor, _ = self._verified_payload(artifact_id)
        return descriptor

    def payload_path(self, artifact_id: ArtifactID) -> Path:
        return self._directory_for(artifact_id) / "payload"

    def manifest_path(self, artifact_id: ArtifactID) -> Path:
        return self._directory_for(artifact_id) / "manifest.json"

    def _directory_for(self, artifact_id: ArtifactID) -> Path:
        return self._artifact_directory_components(artifact_id)[-1]

    def _artifact_directory_components(self, artifact_id: ArtifactID) -> tuple[Path, ...]:
        digest = self._digest_from(artifact_id)
        return (
            self._root,
            self._root / "sha256",
            self._root / "sha256" / digest[:2],
            self._root / "sha256" / digest[:2] / digest[2:4],
            self._root / "sha256" / digest[:2] / digest[2:4] / digest,
        )

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
        directory = self._validate_artifact_directory(artifact_id)
        descriptor = self._load_descriptor(artifact_id, directory)
        payload = self._read_regular_file(directory / "payload", label="payload")
        actual_digest = hashlib.sha256(payload).hexdigest()
        if actual_digest != descriptor.digest:
            raise ArtifactIntegrityError("artifact content hash mismatch")
        if len(payload) != descriptor.size_bytes:
            raise ArtifactIntegrityError("artifact content size mismatch")
        return descriptor, payload

    def _load_descriptor(self, artifact_id: ArtifactID, directory: Path) -> ArtifactDescriptor:
        manifest = self._read_regular_file(directory / "manifest.json", label="manifest")
        manifest_hash = self._read_regular_file(
            directory / "manifest.sha256", label="manifest hash"
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
            path.chmod(0o600)
            return path.read_bytes()
        except OSError as error:
            raise ArtifactIntegrityError(f"artifact {label} cannot be secured or read") from error

    def _prepare_artifact_directory(self, artifact_id: ArtifactID) -> Path:
        components = self._artifact_directory_components(artifact_id)
        for component in components:
            self._ensure_private_directory(component)
        return components[-1]

    def _validate_artifact_directory(self, artifact_id: ArtifactID) -> Path:
        components = self._artifact_directory_components(artifact_id)
        for component in components:
            self._validate_private_directory(component)
        return components[-1]

    @staticmethod
    def _ensure_private_directory(path: Path) -> None:
        if path.is_symlink():
            raise ArtifactIntegrityError("artifact directory must not be a symlink")
        try:
            path.mkdir(mode=0o700)
        except FileExistsError:
            pass
        except OSError as error:
            raise ArtifactIntegrityError("artifact directory cannot be created") from error
        ContentAddressedArtifactStore._validate_private_directory(path)

    @staticmethod
    def _validate_private_directory(path: Path) -> None:
        if path.is_symlink():
            raise ArtifactIntegrityError("artifact directory must not be a symlink")
        if not path.is_dir():
            raise ArtifactIntegrityError("artifact directory is missing")
        try:
            path.chmod(0o700)
        except OSError as error:
            raise ArtifactIntegrityError("artifact directory cannot be secured") from error

    @staticmethod
    def _require_context(context: ArtifactCommandContext) -> ArtifactCommandContext:
        return ArtifactCommandContext.model_validate(context)

    @staticmethod
    def _publish_once(destination: Path, content: bytes) -> None:
        file_descriptor, staging_name = tempfile.mkstemp(
            prefix=".artifact-", dir=destination.parent
        )
        staging_path = Path(staging_name)
        try:
            with os.fdopen(file_descriptor, "wb") as staging_file:
                os.fchmod(staging_file.fileno(), 0o600)
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
            else:
                destination.chmod(0o600)
        finally:
            staging_path.unlink(missing_ok=True)
