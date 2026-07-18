import errno
import hashlib
import json
import os
import secrets
import stat
from contextlib import suppress
from pathlib import Path

from pydantic import ValidationError
from rsi_atlas_contracts import (
    ArtifactCommandContext,
    ArtifactDescriptor,
    ArtifactID,
    ArtifactIntegrityError,
)


class ContentAddressedArtifactStore:
    _STREAM_CHUNK_SIZE = 64 * 1024

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

    def put_file(
        self,
        source: Path,
        *,
        media_type: str,
        max_bytes: int,
        context: ArtifactCommandContext,
    ) -> ArtifactDescriptor:
        context = self._require_context(context)
        if isinstance(max_bytes, bool) or not isinstance(max_bytes, int) or max_bytes < 0:
            raise ValueError("max_bytes must be a non-negative integer")
        source_fd = self._open_staged_source(source)
        try:
            source_state = self._validate_staged_source(source_fd)
            if source_state.st_size > max_bytes:
                raise ArtifactIntegrityError("artifact source exceeds maximum size")
            digest, size_bytes = self._hash_staged_source(
                source_fd,
                source_state=source_state,
                max_bytes=max_bytes,
            )
            descriptor = ArtifactDescriptor(
                artifact_id=ArtifactID(f"sha256:{digest}"),
                digest=digest,
                size_bytes=size_bytes,
                media_type=media_type,
            )
            directory_fd = self._prepare_artifact_directory(descriptor.artifact_id)
            try:
                os.lseek(source_fd, 0, os.SEEK_SET)
                self._publish_source_once(
                    directory_fd,
                    "payload",
                    source_fd,
                    source_state=source_state,
                    expected_digest=digest,
                    expected_size=size_bytes,
                )
                manifest = descriptor.model_dump_json(indent=2).encode("utf-8")
                self._publish_once(directory_fd, "manifest.json", manifest)
                self._publish_once(
                    directory_fd,
                    "manifest.sha256",
                    hashlib.sha256(manifest).hexdigest().encode("ascii"),
                )
            finally:
                os.close(directory_fd)
        finally:
            os.close(source_fd)
        return self.verify(descriptor.artifact_id, context=context)

    def read_bytes(self, artifact_id: ArtifactID, *, context: ArtifactCommandContext) -> bytes:
        self._require_context(context)
        _, payload = self._verified_payload(artifact_id)
        return payload

    def verify(
        self, artifact_id: ArtifactID, *, context: ArtifactCommandContext
    ) -> ArtifactDescriptor:
        self._require_context(context)
        directory_fd = self._validate_artifact_directory(artifact_id)
        try:
            descriptor = self._load_descriptor(artifact_id, directory_fd)
            actual_digest, actual_size = self._hash_regular_file(
                directory_fd,
                "payload",
                label="payload",
                max_bytes=descriptor.size_bytes,
            )
        finally:
            os.close(directory_fd)
        if actual_size != descriptor.size_bytes:
            raise ArtifactIntegrityError("artifact content size mismatch")
        if actual_digest != descriptor.digest:
            raise ArtifactIntegrityError("artifact content hash mismatch")
        return descriptor

    def read_evidence_windows(
        self,
        artifact_id: ArtifactID,
        *,
        context: ArtifactCommandContext,
        leading_bytes: int,
        trailing_bytes: int,
    ) -> tuple[bytes, bytes]:
        self._require_context(context)
        for label, value in (
            ("leading_bytes", leading_bytes),
            ("trailing_bytes", trailing_bytes),
        ):
            if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= 4_096:
                raise ValueError(f"{label} must be an integer in 1..4096")
        directory_fd = self._validate_artifact_directory(artifact_id)
        try:
            descriptor = self._load_descriptor(artifact_id, directory_fd)
            actual_digest, actual_size, leading, trailing = self._verify_with_windows(
                directory_fd,
                "payload",
                label="payload",
                leading_bytes=leading_bytes,
                trailing_bytes=trailing_bytes,
                max_bytes=descriptor.size_bytes,
            )
        finally:
            os.close(directory_fd)
        if actual_size != descriptor.size_bytes:
            raise ArtifactIntegrityError("artifact content size mismatch")
        if actual_digest != descriptor.digest:
            raise ArtifactIntegrityError("artifact content hash mismatch")
        return leading, trailing

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
        file_fd = self._open_regular_file(directory_fd, name, label=label)
        try:
            with os.fdopen(file_fd, "rb") as artifact_file:
                file_fd = -1
                return artifact_file.read()
        finally:
            if file_fd != -1:
                os.close(file_fd)

    def _open_regular_file(self, directory_fd: int, name: str, *, label: str) -> int:
        try:
            file_fd = os.open(name, self._file_open_flags(), dir_fd=directory_fd)
        except OSError as error:
            raise ArtifactIntegrityError(f"artifact {label} is missing or unsafe") from error
        try:
            if not stat.S_ISREG(os.fstat(file_fd).st_mode):
                raise ArtifactIntegrityError(f"artifact {label} is not a regular file")
            os.fchmod(file_fd, 0o600)
            return file_fd
        except BaseException:
            os.close(file_fd)
            raise

    def _hash_regular_file(
        self,
        directory_fd: int,
        name: str,
        *,
        label: str,
        max_bytes: int | None = None,
    ) -> tuple[str, int]:
        file_fd = self._open_regular_file(directory_fd, name, label=label)
        try:
            initial_state = os.fstat(file_fd)
            digest = hashlib.sha256()
            size_bytes = 0
            read_limit = None if max_bytes is None else max_bytes + 1
            while read_limit is None or size_bytes < read_limit:
                read_size = self._STREAM_CHUNK_SIZE
                if read_limit is not None:
                    read_size = min(read_size, read_limit - size_bytes)
                chunk = os.read(file_fd, read_size)
                if not chunk:
                    break
                digest.update(chunk)
                size_bytes += len(chunk)
            if not self._same_file_state(initial_state, os.fstat(file_fd)):
                raise ArtifactIntegrityError(f"artifact {label} changed during verification")
            return digest.hexdigest(), size_bytes
        except OSError as error:
            raise ArtifactIntegrityError(f"artifact {label} cannot be verified") from error
        finally:
            os.close(file_fd)

    def _verify_with_windows(
        self,
        directory_fd: int,
        name: str,
        *,
        label: str,
        leading_bytes: int,
        trailing_bytes: int,
        max_bytes: int,
    ) -> tuple[str, int, bytes, bytes]:
        file_fd = self._open_regular_file(directory_fd, name, label=label)
        try:
            initial_state = os.fstat(file_fd)
            digest = hashlib.sha256()
            leading = bytearray()
            trailing = bytearray()
            size_bytes = 0
            read_limit = max_bytes + 1
            while size_bytes < read_limit:
                chunk = os.read(
                    file_fd,
                    min(self._STREAM_CHUNK_SIZE, read_limit - size_bytes),
                )
                if not chunk:
                    break
                digest.update(chunk)
                if len(leading) < leading_bytes:
                    leading.extend(chunk[: leading_bytes - len(leading)])
                trailing.extend(chunk)
                if len(trailing) > trailing_bytes:
                    del trailing[:-trailing_bytes]
                size_bytes += len(chunk)
            if not self._same_file_state(initial_state, os.fstat(file_fd)):
                raise ArtifactIntegrityError(f"artifact {label} changed during verification")
            return digest.hexdigest(), size_bytes, bytes(leading), bytes(trailing)
        except OSError as error:
            raise ArtifactIntegrityError(f"artifact {label} cannot be verified") from error
        finally:
            os.close(file_fd)

    def _open_staged_source(self, source: Path) -> int:
        absolute_source = Path(os.path.abspath(os.fspath(source)))
        components = absolute_source.parts
        if len(components) < 2 or components[0] != os.path.sep:
            raise ArtifactIntegrityError("artifact source path is unsafe")
        try:
            current_fd = os.open(os.path.sep, self._source_directory_open_flags())
        except OSError as error:
            raise ArtifactIntegrityError("artifact source path is unsafe") from error
        try:
            for component in components[1:-1]:
                child_fd = os.open(
                    component,
                    self._source_directory_open_flags(),
                    dir_fd=current_fd,
                )
                os.close(current_fd)
                current_fd = child_fd
            try:
                return os.open(components[-1], self._file_open_flags(), dir_fd=current_fd)
            except OSError as error:
                raise ArtifactIntegrityError(
                    "artifact source is missing, symlinked, or unsafe"
                ) from error
        except OSError as error:
            raise ArtifactIntegrityError("artifact source path is symlinked or unsafe") from error
        finally:
            os.close(current_fd)

    @staticmethod
    def _validate_staged_source(source_fd: int) -> os.stat_result:
        try:
            source_state = os.fstat(source_fd)
        except OSError as error:
            raise ArtifactIntegrityError("artifact source cannot be inspected") from error
        if not stat.S_ISREG(source_state.st_mode):
            raise ArtifactIntegrityError("artifact source is not a regular file")
        if source_state.st_uid != os.geteuid():
            raise ArtifactIntegrityError("artifact source is not owned by the current user")
        if stat.S_IMODE(source_state.st_mode) & 0o077:
            raise ArtifactIntegrityError("artifact source is not owner-private")
        if source_state.st_nlink != 1:
            raise ArtifactIntegrityError("artifact source has unsafe hard links")
        return source_state

    def _hash_staged_source(
        self,
        source_fd: int,
        *,
        source_state: os.stat_result,
        max_bytes: int,
    ) -> tuple[str, int]:
        digest = hashlib.sha256()
        remaining = source_state.st_size
        size_bytes = 0
        try:
            while remaining:
                chunk = os.read(source_fd, min(self._STREAM_CHUNK_SIZE, remaining))
                if not chunk:
                    raise ArtifactIntegrityError("artifact source produced a short read")
                digest.update(chunk)
                size_bytes += len(chunk)
                remaining -= len(chunk)
            if os.read(source_fd, 1):
                raise ArtifactIntegrityError("artifact source exceeds maximum size")
            if size_bytes > max_bytes:
                raise ArtifactIntegrityError("artifact source exceeds maximum size")
            if not self._same_file_state(source_state, os.fstat(source_fd)):
                raise ArtifactIntegrityError("artifact source changed during hashing")
            return digest.hexdigest(), size_bytes
        except OSError as error:
            raise ArtifactIntegrityError("artifact source cannot be read") from error

    def _publish_source_once(
        self,
        directory_fd: int,
        name: str,
        source_fd: int,
        *,
        source_state: os.stat_result,
        expected_digest: str,
        expected_size: int,
    ) -> None:
        staging_name, staging_fd = self._create_staging_file(directory_fd)
        try:
            actual_digest, actual_size = self._copy_source_to_staging(
                source_fd,
                staging_fd,
                expected_size=expected_size,
            )
            try:
                os.fsync(staging_fd)
            except OSError as error:
                raise ArtifactIntegrityError(
                    "artifact staging file cannot be synchronized"
                ) from error
            if not self._same_file_state(source_state, os.fstat(source_fd)):
                raise ArtifactIntegrityError("artifact source changed during publication")
            if actual_size != expected_size:
                raise ArtifactIntegrityError("artifact source produced a short read")
            if actual_digest != expected_digest:
                raise ArtifactIntegrityError("artifact source changed during publication")
            os.close(staging_fd)
            staging_fd = -1
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
                existing_digest, existing_size = self._hash_regular_file(
                    directory_fd,
                    name,
                    label="stored file",
                    max_bytes=expected_size,
                )
                if existing_digest != expected_digest or existing_size != expected_size:
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

    def _copy_source_to_staging(
        self, source_fd: int, staging_fd: int, *, expected_size: int
    ) -> tuple[str, int]:
        digest = hashlib.sha256()
        remaining = expected_size
        size_bytes = 0
        try:
            while remaining:
                chunk = os.read(source_fd, min(self._STREAM_CHUNK_SIZE, remaining))
                if not chunk:
                    raise ArtifactIntegrityError("artifact source produced a short read")
                self._write_all(staging_fd, chunk)
                digest.update(chunk)
                size_bytes += len(chunk)
                remaining -= len(chunk)
            if os.read(source_fd, 1):
                raise ArtifactIntegrityError("artifact source changed during publication")
            return digest.hexdigest(), size_bytes
        except OSError as error:
            raise ArtifactIntegrityError("artifact source cannot be staged") from error

    @staticmethod
    def _write_all(file_fd: int, content: bytes) -> None:
        remaining = memoryview(content)
        while remaining:
            written = os.write(file_fd, remaining)
            if written == 0:
                raise ArtifactIntegrityError("artifact staging file produced a short write")
            remaining = remaining[written:]

    @staticmethod
    def _same_file_state(first: os.stat_result, second: os.stat_result) -> bool:
        return (
            first.st_dev,
            first.st_ino,
            first.st_mode,
            first.st_nlink,
            first.st_uid,
            first.st_gid,
            first.st_size,
            first.st_mtime_ns,
            first.st_ctime_ns,
        ) == (
            second.st_dev,
            second.st_ino,
            second.st_mode,
            second.st_nlink,
            second.st_uid,
            second.st_gid,
            second.st_size,
            second.st_mtime_ns,
            second.st_ctime_ns,
        )

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
            cleanup_required = True
            try:
                os.fchmod(file_fd, 0o600)
                cleanup_required = False
                return name, file_fd
            except OSError as error:
                raise ArtifactIntegrityError("artifact staging file cannot be secured") from error
            finally:
                if cleanup_required:
                    with suppress(OSError):
                        os.close(file_fd)
                    with suppress(OSError):
                        os.unlink(name, dir_fd=directory_fd)
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
    def _source_directory_open_flags() -> int:
        try:
            return os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
        except AttributeError as error:
            raise ArtifactIntegrityError("secure artifact sources are unsupported") from error

    @staticmethod
    def _staging_open_flags() -> int:
        try:
            return os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW
        except AttributeError as error:
            raise ArtifactIntegrityError("secure artifact files are unsupported") from error
