"""A descriptor-bound, append-only exporter for metadata-only spans."""

from __future__ import annotations

import fcntl
import json
import os
import stat
import threading
import time
from collections.abc import Sequence
from contextlib import suppress
from pathlib import Path
from typing import Final, cast

from opentelemetry.sdk.trace import ReadableSpan
from opentelemetry.sdk.trace.export import SpanExporter, SpanExportResult

from rsi_atlas_observability.redaction import (
    CONTEXT_ATTRIBUTE_NAMES,
    SAFE_ATTRIBUTE_NAMES,
    SafeAttributeValue,
    SensitiveTraceAttributeError,
    TracePolicyError,
    validate_attribute,
    validate_span_name,
)


class TraceStorageError(RuntimeError):
    """Raised when the owner-private trace destination is not trustworthy."""


_SCHEMA_VERSION: Final = "1.0.0"
_MAX_RECORD_BYTES: Final = 64 * 1024
_MAX_FILE_BYTES: Final = 64 * 1024 * 1024
_FILE_MODE: Final = 0o600
_PARENT_MODE: Final = 0o700
_OPEN_DIRECTORY_FLAGS: Final = os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC | os.O_NOFOLLOW
_OPEN_FILE_FLAGS: Final = os.O_RDWR | os.O_APPEND | os.O_CREAT | os.O_CLOEXEC | os.O_NOFOLLOW
_RECORD_KEYS: Final[frozenset[str]] = frozenset(
    {
        "schema_version",
        "name",
        "context",
        "attributes",
        "trace_id",
        "span_id",
        "parent_span_id",
        "start_time_unix_nano",
        "end_time_unix_nano",
        "duration_ns",
        "status_code",
    }
)
_INITIALIZATION_LOCK: Final = threading.Lock()


def _identity(stat_result: os.stat_result) -> tuple[int, int]:
    return (stat_result.st_dev, stat_result.st_ino)


def _mode(stat_result: os.stat_result) -> int:
    return stat.S_IMODE(stat_result.st_mode)


def _require_safe_ancestor(stat_result: os.stat_result, *, is_parent: bool) -> None:
    if not stat.S_ISDIR(stat_result.st_mode):
        raise TraceStorageError("trace parent is not a directory")
    if _mode(stat_result) & 0o022:
        raise TraceStorageError("trace parent has unsafe permissions")
    if is_parent and (stat_result.st_uid != os.getuid() or _mode(stat_result) != _PARENT_MODE):
        raise TraceStorageError("trace parent must be owner-private")


def _require_safe_file(stat_result: os.stat_result) -> None:
    if not stat.S_ISREG(stat_result.st_mode):
        raise TraceStorageError("trace destination is not a regular file")
    if stat_result.st_uid != os.getuid() or _mode(stat_result) != _FILE_MODE:
        raise TraceStorageError("trace destination must be owner-private")
    if stat_result.st_nlink != 1:
        raise TraceStorageError("trace destination must not be hard linked")


class LocalJSONLSpanExporter(SpanExporter):
    """Export only fully validated spans to one current-user-owned JSONL file."""

    def __init__(self, destination: Path) -> None:
        self._destination = destination
        if not destination.is_absolute():
            raise TraceStorageError("trace destination must be absolute")
        if destination.name in {"", ".", ".."}:
            raise TraceStorageError("trace destination name is invalid")
        self._parent_path = destination.parent
        self._lock = threading.RLock()
        self._shutdown = False
        self._poisoned = False
        self._last_error: str | None = None
        self._parent_fd = -1
        self._file_fd = -1
        self._parent_identity: tuple[int, int] | None = None
        self._file_identity: tuple[int, int] | None = None
        self._validated_size = 0
        with _INITIALIZATION_LOCK:
            try:
                self._parent_fd, self._parent_identity = self._open_parent()
                fcntl.flock(self._parent_fd, fcntl.LOCK_EX)
                try:
                    self._file_fd = os.open(
                        destination.name,
                        _OPEN_FILE_FLAGS,
                        _FILE_MODE,
                        dir_fd=self._parent_fd,
                    )
                    file_stat = os.fstat(self._file_fd)
                    _require_safe_file(file_stat)
                    self._file_identity = _identity(file_stat)
                    fcntl.flock(self._file_fd, fcntl.LOCK_EX)
                    try:
                        self._validate_existing_file()
                    finally:
                        fcntl.flock(self._file_fd, fcntl.LOCK_UN)
                finally:
                    fcntl.flock(self._parent_fd, fcntl.LOCK_UN)
            except Exception as error:
                self._close_descriptors()
                if isinstance(error, TraceStorageError):
                    raise
                raise TraceStorageError("trace storage could not be opened") from error

    @property
    def destination(self) -> Path:
        return self._destination

    @property
    def last_error(self) -> str | None:
        return self._last_error

    def _open_parent(self) -> tuple[int, tuple[int, int]]:
        parent = self._parent_path
        parts = parent.parts
        if not parts or parts[0] != os.sep:
            raise TraceStorageError("trace destination must be absolute")
        descriptor = os.open(os.sep, _OPEN_DIRECTORY_FLAGS)
        try:
            for index, part in enumerate(parts[1:], start=1):
                next_descriptor = os.open(part, _OPEN_DIRECTORY_FLAGS, dir_fd=descriptor)
                os.close(descriptor)
                descriptor = next_descriptor
                _require_safe_ancestor(os.fstat(descriptor), is_parent=index == len(parts) - 1)
            if len(parts) == 1:
                _require_safe_ancestor(os.fstat(descriptor), is_parent=True)
            return descriptor, _identity(os.fstat(descriptor))
        except Exception:
            os.close(descriptor)
            raise

    def _revalidate_bound_descriptors(self) -> None:
        if self._parent_identity is None or self._file_identity is None:
            raise TraceStorageError("trace storage is closed")
        fresh_parent_fd, fresh_parent_identity = self._open_parent()
        try:
            if fresh_parent_identity != self._parent_identity:
                raise TraceStorageError("trace parent changed after open")
        finally:
            os.close(fresh_parent_fd)
        parent_stat = os.fstat(self._parent_fd)
        file_stat = os.fstat(self._file_fd)
        _require_safe_ancestor(parent_stat, is_parent=True)
        _require_safe_file(file_stat)
        if (
            _identity(parent_stat) != self._parent_identity
            or _identity(file_stat) != self._file_identity
        ):
            raise TraceStorageError("trace storage changed after open")
        path_stat = os.stat(self._destination.name, dir_fd=self._parent_fd, follow_symlinks=False)
        _require_safe_file(path_stat)
        if _identity(path_stat) != self._file_identity:
            raise TraceStorageError("trace destination changed after open")

    def _validate_existing_file(self) -> None:
        file_size = os.fstat(self._file_fd).st_size
        if file_size > _MAX_FILE_BYTES:
            raise TraceStorageError("existing trace storage exceeds maximum size")
        os.lseek(self._file_fd, 0, os.SEEK_SET)
        payload = bytearray()
        while len(payload) <= _MAX_FILE_BYTES:
            block = os.read(self._file_fd, min(64 * 1024, _MAX_FILE_BYTES + 1 - len(payload)))
            if not block:
                break
            payload.extend(block)
        if len(payload) > _MAX_FILE_BYTES:
            raise TraceStorageError("existing trace storage exceeds maximum size")
        self._validate_jsonl_payload(bytes(payload))
        self._validated_size = file_size
        os.lseek(self._file_fd, 0, os.SEEK_END)

    def _validate_jsonl_payload(self, payload: bytes) -> None:
        if payload and not payload.endswith(b"\n"):
            raise TraceStorageError("existing trace storage is invalid")
        for line in payload.splitlines(keepends=True):
            raw_record = line[:-1]
            if not raw_record or len(raw_record) > _MAX_RECORD_BYTES:
                raise TraceStorageError("existing trace storage is invalid")
            try:
                decoded = raw_record.decode("utf-8")
                parsed = json.loads(decoded)
            except (UnicodeDecodeError, json.JSONDecodeError) as error:
                raise TraceStorageError("existing trace storage is invalid") from error
            self._validate_record(parsed)
            canonical = json.dumps(parsed, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
            if canonical != decoded:
                raise TraceStorageError("existing trace storage is invalid")

    def _validate_shared_tail(self) -> None:
        file_size = os.fstat(self._file_fd).st_size
        if file_size < self._validated_size or file_size > _MAX_FILE_BYTES:
            raise TraceStorageError("trace storage size is invalid")
        remaining = file_size - self._validated_size
        if remaining == 0:
            return
        payload = bytearray()
        while len(payload) < remaining:
            block = os.pread(
                self._file_fd,
                min(64 * 1024, remaining - len(payload)),
                self._validated_size + len(payload),
            )
            if not block:
                raise TraceStorageError("trace storage tail is invalid")
            payload.extend(block)
        self._validate_jsonl_payload(bytes(payload))
        self._validated_size = file_size

    def _validate_record(self, record: object) -> None:
        if type(record) is not dict or set(record) != _RECORD_KEYS:
            raise TraceStorageError("existing trace storage is invalid")
        typed = cast(dict[str, object], record)
        if typed["schema_version"] != _SCHEMA_VERSION:
            raise TraceStorageError("existing trace storage is invalid")
        try:
            name = typed["name"]
            if type(name) is not str:
                raise TracePolicyError("name is invalid")
            validate_span_name(name)
            context = typed["context"]
            attributes = typed["attributes"]
            if type(context) is not dict or set(context) != set(CONTEXT_ATTRIBUTE_NAMES.values()):
                raise TracePolicyError("context is invalid")
            for attribute_name, context_name in CONTEXT_ATTRIBUTE_NAMES.items():
                validate_attribute(attribute_name, context[context_name])
            if type(attributes) is not dict:
                raise TracePolicyError("attributes are invalid")
            for name, value in attributes.items():
                if name in CONTEXT_ATTRIBUTE_NAMES or name not in SAFE_ATTRIBUTE_NAMES:
                    raise TracePolicyError("attributes are invalid")
                validate_attribute(name, value)
        except (KeyError, TracePolicyError, SensitiveTraceAttributeError) as error:
            raise TraceStorageError("existing trace storage is invalid") from error
        for key, width in (("trace_id", 32), ("span_id", 16)):
            value = typed[key]
            if (
                type(value) is not str
                or len(value) != width
                or any(character not in "0123456789abcdef" for character in value)
            ):
                raise TraceStorageError("existing trace storage is invalid")
            if int(value, 16) == 0:
                raise TraceStorageError("existing trace storage is invalid")
        parent = typed["parent_span_id"]
        if parent is not None and (
            type(parent) is not str
            or len(parent) != 16
            or any(character not in "0123456789abcdef" for character in parent)
        ):
            raise TraceStorageError("existing trace storage is invalid")
        if parent is not None and int(parent, 16) == 0:
            raise TraceStorageError("existing trace storage is invalid")
        for key in ("start_time_unix_nano", "end_time_unix_nano", "duration_ns"):
            if type(typed[key]) is not int or cast(int, typed[key]) < 0:
                raise TraceStorageError("existing trace storage is invalid")
        if cast(int, typed["end_time_unix_nano"]) < cast(int, typed["start_time_unix_nano"]):
            raise TraceStorageError("existing trace storage is invalid")
        expected_duration = cast(int, typed["end_time_unix_nano"]) - cast(
            int, typed["start_time_unix_nano"]
        )
        if typed["duration_ns"] != expected_duration:
            raise TraceStorageError("existing trace storage is invalid")
        if typed["status_code"] not in {"UNSET", "OK", "ERROR"}:
            raise TraceStorageError("existing trace storage is invalid")

    def _span_record(self, span: ReadableSpan) -> dict[str, object]:
        if dict(span.resource.attributes):
            raise TraceStorageError("span resource attributes are not permitted")
        if span.events or span.links or span.status.description:
            raise TraceStorageError("span events, links, or status descriptions are not permitted")
        name = validate_span_name(span.name)
        raw_attributes = dict(span.attributes or {})
        if set(CONTEXT_ATTRIBUTE_NAMES) - set(raw_attributes):
            raise TraceStorageError("span mandatory context is missing")
        safe_attributes: dict[str, SafeAttributeValue] = {}
        context: dict[str, str] = {}
        for attribute_name, value in raw_attributes.items():
            validated = validate_attribute(attribute_name, value)
            if attribute_name in CONTEXT_ATTRIBUTE_NAMES:
                context[CONTEXT_ATTRIBUTE_NAMES[attribute_name]] = cast(str, validated)
            else:
                safe_attributes[attribute_name] = validated
        if set(context) != set(CONTEXT_ATTRIBUTE_NAMES.values()):
            raise TraceStorageError("span mandatory context is missing")
        span_context = span.get_span_context()
        if span_context is None:
            raise TraceStorageError("span context is invalid")
        parent_context = span.parent
        if not self._valid_identifier(span_context.trace_id, 32) or not self._valid_identifier(
            span_context.span_id, 16
        ):
            raise TraceStorageError("span context is invalid")
        if parent_context is not None and not self._valid_identifier(parent_context.span_id, 16):
            raise TraceStorageError("span parent context is invalid")
        start = span.start_time
        end = span.end_time
        if start is None or end is None or start < 0 or end < start:
            raise TraceStorageError("span timing is invalid")
        return {
            "schema_version": _SCHEMA_VERSION,
            "name": name,
            "context": context,
            "attributes": safe_attributes,
            "trace_id": f"{span_context.trace_id:032x}",
            "span_id": f"{span_context.span_id:016x}",
            "parent_span_id": (
                f"{parent_context.span_id:016x}" if parent_context is not None else None
            ),
            "start_time_unix_nano": start,
            "end_time_unix_nano": end,
            "duration_ns": end - start,
            "status_code": span.status.status_code.name,
        }

    @staticmethod
    def _valid_identifier(value: object, width: int) -> bool:
        return type(value) is int and 0 < value < 1 << (width * 4)

    def _encode_record(self, record: dict[str, object]) -> bytes:
        canonical = json.dumps(record, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
        encoded = canonical.encode("utf-8") + b"\n"
        if len(encoded) > _MAX_RECORD_BYTES:
            raise TraceStorageError("trace record exceeds maximum size")
        return encoded

    def _write_all(self, payload: bytes) -> None:
        view = memoryview(payload)
        while view:
            written = os.write(self._file_fd, view)
            if written <= 0:
                raise TraceStorageError("trace storage write failed")
            view = view[written:]

    def export(self, spans: Sequence[ReadableSpan]) -> SpanExportResult:
        with self._lock:
            if self._shutdown:
                self._last_error = "trace exporter is shut down"
                return SpanExportResult.FAILURE
            if self._poisoned:
                self._last_error = "trace exporter is poisoned"
                return SpanExportResult.FAILURE
            try:
                payloads = [self._encode_record(self._span_record(span)) for span in spans]
                self._revalidate_bound_descriptors()
                for payload in payloads:
                    fcntl.flock(self._file_fd, fcntl.LOCK_EX)
                    try:
                        self._revalidate_bound_descriptors()
                        self._validate_shared_tail()
                        if os.fstat(self._file_fd).st_size + len(payload) > _MAX_FILE_BYTES:
                            raise TraceStorageError("trace storage exceeds maximum size")
                        self._write_all(payload)
                        os.fsync(self._file_fd)
                        self._validated_size += len(payload)
                    finally:
                        fcntl.flock(self._file_fd, fcntl.LOCK_UN)
                self._last_error = None
                return SpanExportResult.SUCCESS
            except (OSError, TracePolicyError, TraceStorageError):
                self._poisoned = True
                self._last_error = "trace exporter is poisoned"
                self._close_descriptors()
                return SpanExportResult.FAILURE

    def force_flush(self, timeout_millis: int = 30_000) -> bool:
        with self._lock:
            if self._shutdown or self._poisoned or timeout_millis < 0:
                return False
            try:
                self._revalidate_bound_descriptors()
                deadline = time.monotonic() + timeout_millis / 1000
                while True:
                    try:
                        fcntl.flock(self._file_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                        break
                    except BlockingIOError:
                        if time.monotonic() >= deadline:
                            self._last_error = "trace storage flush lock timed out"
                            return False
                        time.sleep(0.001)
                try:
                    self._revalidate_bound_descriptors()
                    self._validate_shared_tail()
                    os.fsync(self._file_fd)
                finally:
                    fcntl.flock(self._file_fd, fcntl.LOCK_UN)
                self._last_error = None
                return True
            except (OSError, TraceStorageError):
                self._last_error = "trace storage flush failed"
                return False

    def shutdown(self) -> None:
        with self._lock:
            if self._shutdown:
                return
            if not self._poisoned:
                self.force_flush()
            self._shutdown = True
            self._close_descriptors()

    def _close_descriptors(self) -> None:
        for descriptor in (self._file_fd, self._parent_fd):
            if descriptor >= 0:
                with suppress(OSError):
                    os.close(descriptor)
        self._file_fd = -1
        self._parent_fd = -1
