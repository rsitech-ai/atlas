import hashlib
import os
import secrets
import stat
from collections.abc import AsyncIterable
from dataclasses import dataclass
from pathlib import Path

from rsi_atlas_contracts import SafetyCheckState
from rsi_atlas_ingestion import MAX_PDF_BYTES, StagedPDFEvidence

_CHUNK_BYTES = 64 * 1024
_DISK_RESERVE_BYTES = 64 * 1024 * 1024


class ImportStagingError(RuntimeError):
    """Raised when an untrusted import cannot be staged without weakening its boundary."""


@dataclass(frozen=True, slots=True)
class StagedPDF:
    path: Path
    evidence: StagedPDFEvidence
    _device: int
    _inode: int

    def cleanup(self) -> None:
        parent_fd = -1
        file_fd = -1
        try:
            parent_fd = os.open(self.path.parent, _directory_open_flags())
            file_fd = os.open(self.path.name, _file_open_flags(), dir_fd=parent_fd)
            state = os.fstat(file_fd)
            if (state.st_dev, state.st_ino) != (self._device, self._inode):
                raise ImportStagingError("staged PDF changed before cleanup")
            os.unlink(self.path.name, dir_fd=parent_fd)
        except FileNotFoundError:
            return
        except ImportStagingError:
            raise
        except OSError as error:
            raise ImportStagingError("staged PDF cannot be cleaned up safely") from error
        finally:
            if file_fd >= 0:
                os.close(file_fd)
            if parent_fd >= 0:
                os.close(parent_fd)


class ImportStagingArea:
    def __init__(self, root: Path) -> None:
        if not isinstance(root, Path) or not root.is_absolute():
            raise ImportStagingError("import staging root must be absolute")
        if root != Path(os.path.normpath(root)):
            raise ImportStagingError("import staging root must be canonical")
        self._root = root
        root_fd = self._open_root()
        os.close(root_fd)

    async def stage_chunks(
        self,
        chunks: AsyncIterable[bytes],
        *,
        expected_bytes: int,
    ) -> StagedPDF:
        _require_expected_size(expected_bytes)
        self._require_disk_capacity(expected_bytes)
        root_fd, name, destination_fd = self._create_file()
        accumulator = _EvidenceAccumulator()
        try:
            async for chunk in chunks:
                if not isinstance(chunk, bytes):
                    raise ImportStagingError("request body chunks must be bytes")
                if not chunk:
                    continue
                if accumulator.size_bytes + len(chunk) > expected_bytes:
                    raise ImportStagingError("request body length exceeds Content-Length")
                _write_all(destination_fd, chunk)
                accumulator.update(chunk)
            if accumulator.size_bytes != expected_bytes:
                raise ImportStagingError("request body length differs from Content-Length")
            os.fsync(destination_fd)
            state = os.fstat(destination_fd)
            evidence = accumulator.evidence()
            os.close(destination_fd)
            destination_fd = -1
            return StagedPDF(
                path=self._root / name,
                evidence=evidence,
                _device=state.st_dev,
                _inode=state.st_ino,
            )
        except BaseException:
            _cleanup_incomplete(root_fd, name, destination_fd)
            destination_fd = -1
            raise
        finally:
            if destination_fd >= 0:
                os.close(destination_fd)
            os.close(root_fd)

    def stage_file(self, source: Path) -> StagedPDF:
        source_fd = _open_source(source)
        try:
            source_state = os.fstat(source_fd)
            if not stat.S_ISREG(source_state.st_mode):
                raise ImportStagingError("import source is not a regular file")
            _require_expected_size(source_state.st_size)
            self._require_disk_capacity(source_state.st_size)
            root_fd, name, destination_fd = self._create_file()
            accumulator = _EvidenceAccumulator()
            try:
                remaining = source_state.st_size
                while remaining:
                    chunk = os.read(source_fd, min(_CHUNK_BYTES, remaining))
                    if not chunk:
                        raise ImportStagingError("import source produced a short read")
                    _write_all(destination_fd, chunk)
                    accumulator.update(chunk)
                    remaining -= len(chunk)
                if os.read(source_fd, 1):
                    raise ImportStagingError("import source changed during staging")
                if _file_identity(source_state) != _file_identity(os.fstat(source_fd)):
                    raise ImportStagingError("import source changed during staging")
                os.fsync(destination_fd)
                destination_state = os.fstat(destination_fd)
                evidence = accumulator.evidence()
                os.close(destination_fd)
                destination_fd = -1
                return StagedPDF(
                    path=self._root / name,
                    evidence=evidence,
                    _device=destination_state.st_dev,
                    _inode=destination_state.st_ino,
                )
            except BaseException:
                _cleanup_incomplete(root_fd, name, destination_fd)
                destination_fd = -1
                raise
            finally:
                if destination_fd >= 0:
                    os.close(destination_fd)
                os.close(root_fd)
        except ImportStagingError:
            raise
        except OSError as error:
            raise ImportStagingError("import source cannot be read safely") from error
        finally:
            os.close(source_fd)

    def _open_root(self) -> int:
        try:
            root_fd = os.open(self._root, _directory_open_flags())
            state = os.fstat(root_fd)
            if (
                not stat.S_ISDIR(state.st_mode)
                or state.st_uid != os.geteuid()
                or stat.S_IMODE(state.st_mode) != 0o700
            ):
                raise ImportStagingError("import staging root must be owner-private")
            return root_fd
        except ImportStagingError:
            if "root_fd" in locals():
                os.close(root_fd)
            raise
        except OSError as error:
            raise ImportStagingError("import staging root is missing or unsafe") from error

    def _create_file(self) -> tuple[int, str, int]:
        root_fd = self._open_root()
        for _ in range(8):
            name = f".import-{secrets.token_hex(16)}"
            try:
                file_fd = os.open(
                    name,
                    _staging_open_flags(),
                    mode=0o600,
                    dir_fd=root_fd,
                )
                os.fchmod(file_fd, 0o600)
                return root_fd, name, file_fd
            except FileExistsError:
                continue
            except OSError as error:
                os.close(root_fd)
                raise ImportStagingError("staging file cannot be created safely") from error
        os.close(root_fd)
        raise ImportStagingError("staging file name collision")

    def _require_disk_capacity(self, expected_bytes: int) -> None:
        try:
            filesystem = os.statvfs(self._root)
        except OSError as error:
            raise ImportStagingError("available disk cannot be inspected") from error
        available = filesystem.f_bavail * filesystem.f_frsize
        if available < expected_bytes + _DISK_RESERVE_BYTES:
            raise ImportStagingError("available disk is insufficient for import staging")


class _EvidenceAccumulator:
    def __init__(self) -> None:
        self._digest = hashlib.sha256()
        self._leading = bytearray()
        self._trailing = bytearray()
        self.size_bytes = 0

    def update(self, chunk: bytes) -> None:
        self._digest.update(chunk)
        if len(self._leading) < 8:
            self._leading.extend(chunk[: 8 - len(self._leading)])
        self._trailing.extend(chunk)
        if len(self._trailing) > 1_024:
            del self._trailing[:-1_024]
        self.size_bytes += len(chunk)

    def evidence(self) -> StagedPDFEvidence:
        return StagedPDFEvidence(
            digest=self._digest.hexdigest(),
            size_bytes=self.size_bytes,
            leading_bytes=bytes(self._leading),
            trailing_bytes=bytes(self._trailing),
            source_policy=SafetyCheckState.PASS,
            available_disk=SafetyCheckState.PASS,
        )


def _open_source(source: Path) -> int:
    if not isinstance(source, Path):
        raise TypeError("import source must be a pathlib.Path")
    absolute = Path(os.path.abspath(os.fspath(source)))
    components = absolute.parts
    if len(components) < 2 or components[0] != os.path.sep:
        raise ImportStagingError("import source path is unsafe")
    current_fd = os.open(os.path.sep, _directory_open_flags())
    try:
        for component in components[1:-1]:
            next_fd = os.open(component, _directory_open_flags(), dir_fd=current_fd)
            os.close(current_fd)
            current_fd = next_fd
        try:
            return os.open(components[-1], _file_open_flags(), dir_fd=current_fd)
        except OSError as error:
            raise ImportStagingError("import source is missing, symlinked, or unsafe") from error
    except ImportStagingError:
        raise
    except OSError as error:
        raise ImportStagingError("import source path is symlinked or unsafe") from error
    finally:
        os.close(current_fd)


def _cleanup_incomplete(root_fd: int, name: str, file_fd: int) -> None:
    if file_fd >= 0:
        os.close(file_fd)
    try:
        os.unlink(name, dir_fd=root_fd)
    except FileNotFoundError:
        pass
    except OSError as error:
        raise ImportStagingError("incomplete staging file cannot be removed") from error


def _write_all(file_fd: int, content: bytes) -> None:
    remaining = memoryview(content)
    while remaining:
        try:
            written = os.write(file_fd, remaining)
        except OSError as error:
            raise ImportStagingError("staging file cannot be written") from error
        if written == 0:
            raise ImportStagingError("staging file produced a short write")
        remaining = remaining[written:]


def _require_expected_size(value: int) -> None:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError("import size must be an integer")
    if not 1 <= value <= MAX_PDF_BYTES:
        raise ImportStagingError("import size is outside the PDF limit")


def _file_identity(state: os.stat_result) -> tuple[int, ...]:
    return (
        state.st_dev,
        state.st_ino,
        state.st_mode,
        state.st_nlink,
        state.st_uid,
        state.st_gid,
        state.st_size,
        state.st_mtime_ns,
        state.st_ctime_ns,
    )


def _directory_open_flags() -> int:
    try:
        return os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    except AttributeError as error:
        raise ImportStagingError("secure import directories are unsupported") from error


def _file_open_flags() -> int:
    try:
        return os.O_RDONLY | os.O_NOFOLLOW
    except AttributeError as error:
        raise ImportStagingError("secure import files are unsupported") from error


def _staging_open_flags() -> int:
    try:
        return os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW
    except AttributeError as error:
        raise ImportStagingError("secure import files are unsupported") from error
