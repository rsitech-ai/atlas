import errno
import hashlib
import json
import os
import secrets
import stat
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
        directory_fd = self._prepare_artifact_directory(descriptor.artifact_id)
        try:
            manifest = descriptor.model_dump_json(indent=2).encode("utf-8")
            self._publish_once(directory_fd, "payload", payload)
            self._publish_once(directory_fd, "manifest.json", manifest)
            self._publish_once(
                directory_fd,
                "manifest.sha256",
                hashlib.sha256(manifest).hexdigest().encode("ascii"),
            )
        finally:
            os.close(directory_fd)
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
        digest = self._digest_from(artifact_id)
        return self._root / "sha256" / digest[:2] / digest[2:4] / digest

    def _artifact_directory_components(self, artifact_id: ArtifactID) -> tuple[str, ...]:
        digest = self._digest_from(artifact_id)
        return "sha256", digest[:2], digest[2:4], digest

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
        directory_fd = self._validate_artifact_directory(artifact_id)
        try:
            descriptor = self._load_descriptor(artifact_id, directory_fd)
            payload = self._read_regular_file(directory_fd, "payload", label="payload")
        finally:
            os.close(directory_fd)
        actual_digest = hashlib.sha256(payload).hexdigest()
        if actual_digest != descriptor.digest:
            raise ArtifactIntegrityError("artifact content hash mismatch")
        if len(payload) != descriptor.size_bytes:
            raise ArtifactIntegrityError("artifact content size mismatch")
        return descriptor, payload

    def _load_descriptor(self, artifact_id: ArtifactID, directory_fd: int) -> ArtifactDescriptor:
        manifest = self._read_regular_file(directory_fd, "manifest.json", label="manifest")
        manifest_hash = self._read_regular_file(
            directory_fd, "manifest.sha256", label="manifest hash"
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

    def _prepare_artifact_directory(self, artifact_id: ArtifactID) -> int:
        return self._open_artifact_directory(artifact_id, create=True)

    def _validate_artifact_directory(self, artifact_id: ArtifactID) -> int:
        return self._open_artifact_directory(artifact_id, create=False)

    def _open_artifact_directory(self, artifact_id: ArtifactID, *, create: bool) -> int:
        current_fd = self._open_root(create=create)
        try:
            for component in self._artifact_directory_components(artifact_id):
                child_fd = self._open_child_directory(current_fd, component, create=create)
                os.close(current_fd)
                current_fd = child_fd
            return current_fd
        except BaseException:
            os.close(current_fd)
            raise

    def _open_root(self, *, create: bool) -> int:
        if create:
            try:
                os.mkdir(self._root, mode=0o700)
            except FileExistsError:
                pass
            except OSError as error:
                raise ArtifactIntegrityError("artifact root cannot be created") from error
        return self._open_private_directory(self._root, label="artifact root")

    def _open_child_directory(self, parent_fd: int, name: str, *, create: bool) -> int:
        if create:
            try:
                os.mkdir(name, mode=0o700, dir_fd=parent_fd)
            except FileExistsError:
                pass
            except OSError as error:
                raise ArtifactIntegrityError("artifact directory cannot be created") from error
        return self._open_private_directory(name, parent_fd=parent_fd, label="artifact directory")

    def _open_private_directory(
        self, path: str | Path, *, parent_fd: int | None = None, label: str
    ) -> int:
        try:
            directory_fd = os.open(path, self._directory_open_flags(), dir_fd=parent_fd)
        except OSError as error:
            if error.errno in {errno.ELOOP, errno.ENOTDIR}:
                raise ArtifactIntegrityError(
                    f"{label} must not be a symlink or non-directory"
                ) from error
            raise ArtifactIntegrityError(f"{label} is missing or unsafe") from error
        try:
            if not stat.S_ISDIR(os.fstat(directory_fd).st_mode):
                raise ArtifactIntegrityError(f"{label} is not a directory")
            os.fchmod(directory_fd, 0o700)
            return directory_fd
        except BaseException:
            os.close(directory_fd)
            raise

    def _read_regular_file(self, directory_fd: int, name: str, *, label: str) -> bytes:
        try:
            file_fd = os.open(name, self._file_open_flags(), dir_fd=directory_fd)
        except OSError as error:
            raise ArtifactIntegrityError(f"artifact {label} is missing or unsafe") from error
        try:
            if not stat.S_ISREG(os.fstat(file_fd).st_mode):
                raise ArtifactIntegrityError(f"artifact {label} is not a regular file")
            os.fchmod(file_fd, 0o600)
            with os.fdopen(file_fd, "rb") as artifact_file:
                file_fd = -1
                return artifact_file.read()
        finally:
            if file_fd != -1:
                os.close(file_fd)

    def _publish_once(self, directory_fd: int, name: str, content: bytes) -> None:
        staging_name, staging_fd = self._create_staging_file(directory_fd)
        try:
            with os.fdopen(staging_fd, "wb") as staging_file:
                staging_fd = -1
                staging_file.write(content)
                staging_file.flush()
                os.fsync(staging_file.fileno())
            try:
                os.link(
                    staging_name,
                    name,
                    src_dir_fd=directory_fd,
                    dst_dir_fd=directory_fd,
                    follow_symlinks=False,
                )
            except (NotImplementedError, TypeError) as error:
                raise ArtifactIntegrityError(
                    "secure artifact publication is unsupported"
                ) from error
            except FileExistsError as error:
                existing = self._read_regular_file(directory_fd, name, label="stored file")
                if existing != content:
                    raise ArtifactIntegrityError(
                        "existing immutable artifact file differs"
                    ) from error
        finally:
            if staging_fd != -1:
                os.close(staging_fd)
            try:
                os.unlink(staging_name, dir_fd=directory_fd)
            except FileNotFoundError:
                pass
            except OSError as error:
                raise ArtifactIntegrityError("artifact staging file cannot be removed") from error

    def _create_staging_file(self, directory_fd: int) -> tuple[str, int]:
        for _ in range(8):
            name = f".artifact-{secrets.token_hex(16)}"
            try:
                file_fd = os.open(
                    name,
                    self._staging_open_flags(),
                    mode=0o600,
                    dir_fd=directory_fd,
                )
            except FileExistsError:
                continue
            except OSError as error:
                raise ArtifactIntegrityError("artifact staging file cannot be created") from error
            os.fchmod(file_fd, 0o600)
            return name, file_fd
        raise ArtifactIntegrityError("artifact staging file name collision")

    @staticmethod
    def _require_context(context: ArtifactCommandContext) -> ArtifactCommandContext:
        return ArtifactCommandContext.model_validate(context)

    @staticmethod
    def _directory_open_flags() -> int:
        try:
            return os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
        except AttributeError as error:
            raise ArtifactIntegrityError("secure artifact directories are unsupported") from error

    @staticmethod
    def _file_open_flags() -> int:
        try:
            return os.O_RDONLY | os.O_NOFOLLOW
        except AttributeError as error:
            raise ArtifactIntegrityError("secure artifact files are unsupported") from error

    @staticmethod
    def _staging_open_flags() -> int:
        try:
            return os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW
        except AttributeError as error:
            raise ArtifactIntegrityError("secure artifact files are unsupported") from error
