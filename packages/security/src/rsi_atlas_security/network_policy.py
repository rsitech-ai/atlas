from __future__ import annotations

import ipaddress
import os
import re
import stat
from collections.abc import Iterable
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from urllib.parse import SplitResult, urlsplit

_DNS_LABEL = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$")
_REMOTE_SCHEMES = frozenset({"https"})
_LOOPBACK_SCHEMES = frozenset({"http", "https"})


class RuntimeProfile(StrEnum):
    OFFLINE = "offline"
    MONITORED = "monitored"


class ProcessRole(StrEnum):
    API = "atlas-api"
    ENGINE = "atlas-engine"
    DOCUMENT_WORKER = "atlas-worker-document"
    MODEL_WORKER = "atlas-worker-model"
    DATA_WORKER = "atlas-worker-data"
    EVALUATION_WORKER = "atlas-worker-evaluation"
    COLLECTOR = "atlas-collector"
    EXPORTER = "atlas-exporter"
    CODEX_CONTROLLER = "atlas-codex-controller"


@dataclass(frozen=True, slots=True)
class NetworkDecision:
    allowed: bool
    reason: str
    canonical_destination: str | None
    profile: RuntimeProfile
    role: ProcessRole


def _parse_role(role: ProcessRole | str) -> ProcessRole:
    try:
        return ProcessRole(role)
    except ValueError as error:
        raise ValueError("unknown RSI Atlas process role") from error


def _parse_origin(origin: str, *, kind: str) -> SplitResult:
    if not isinstance(origin, str) or not origin or not origin.isascii():
        raise ValueError(f"invalid {kind}")
    parsed = urlsplit(origin)
    if (
        not parsed.scheme
        or not parsed.netloc
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError(f"invalid {kind}")
    try:
        port = parsed.port
    except ValueError as error:
        raise ValueError(f"invalid {kind}") from error
    if parsed.hostname is None or port is None or not 1 <= port <= 65535:
        raise ValueError(f"invalid {kind}")
    return parsed


def _validated_port(port: int) -> int:
    if isinstance(port, bool) or not isinstance(port, int) or not 1 <= port <= 65535:
        raise ValueError("invalid destination port")
    return port


def _validated_dns_host(host: str) -> str:
    if not isinstance(host, str) or not host or not host.isascii():
        raise ValueError("invalid remote origin")
    canonical = host.lower()
    if (
        canonical.endswith(".")
        or canonical == "localhost"
        or "*" in canonical
        or "%" in canonical
        or re.fullmatch(r"[0-9.]+", canonical) is not None
    ):
        raise ValueError("invalid remote origin")
    try:
        ipaddress.ip_address(canonical)
    except ValueError:
        pass
    else:
        raise ValueError("invalid remote origin")
    labels = canonical.split(".")
    if len(labels) < 2 or any(not _DNS_LABEL.fullmatch(label) for label in labels):
        raise ValueError("invalid remote origin")
    return canonical


def canonical_remote_origin(origin: str) -> str:
    parsed = _parse_origin(origin, kind="remote origin")
    scheme = parsed.scheme.lower()
    if scheme not in _REMOTE_SCHEMES:
        raise ValueError("invalid remote origin")
    host = _validated_dns_host(parsed.hostname or "")
    return f"{scheme}://{host}:{parsed.port}"


def _canonical_remote_components(*, scheme: str, host: str, port: int) -> str:
    if not isinstance(scheme, str) or scheme.lower() not in _REMOTE_SCHEMES:
        raise ValueError("invalid remote origin")
    canonical_host = _validated_dns_host(host)
    return f"{scheme.lower()}://{canonical_host}:{_validated_port(port)}"


def _canonical_loopback_origin(origin: str) -> str:
    parsed = _parse_origin(origin, kind="loopback origin")
    scheme = parsed.scheme.lower()
    if scheme not in _LOOPBACK_SCHEMES:
        raise ValueError("invalid loopback origin")
    try:
        address = ipaddress.ip_address(parsed.hostname or "")
    except ValueError as error:
        raise ValueError("invalid loopback origin") from error
    if not address.is_loopback:
        raise ValueError("invalid loopback origin")
    host = f"[{address.compressed}]" if address.version == 6 else address.compressed
    return f"{scheme}://{host}:{parsed.port}"


def _canonical_loopback_components(*, scheme: str, host: str, port: int) -> str:
    if not isinstance(scheme, str) or scheme.lower() not in _LOOPBACK_SCHEMES:
        raise ValueError("invalid loopback origin")
    try:
        address = ipaddress.ip_address(host)
    except ValueError as error:
        raise ValueError("invalid loopback origin") from error
    if not address.is_loopback:
        raise ValueError("invalid loopback origin")
    rendered = f"[{address.compressed}]" if address.version == 6 else address.compressed
    return f"{scheme.lower()}://{rendered}:{_validated_port(port)}"


def _canonical_unique_origins(
    origins: Iterable[str],
    *,
    canonicalizer: object,
    kind: str,
) -> frozenset[str]:
    if isinstance(origins, (str, bytes)):
        raise ValueError(f"{kind} collection is invalid")
    values: set[str] = set()
    for origin in origins:
        if canonicalizer is canonical_remote_origin:
            canonical = canonical_remote_origin(origin)
        else:
            canonical = _canonical_loopback_origin(origin)
        if canonical in values:
            raise ValueError(f"duplicate {kind}")
        values.add(canonical)
    return frozenset(values)


def _validate_unix_socket(path: Path) -> str:
    if not path.is_absolute():
        raise ValueError("Unix socket path must be absolute")
    if path != Path(os.path.normpath(path)):
        raise ValueError("Unix socket path must be canonical")
    flags = os.O_RDONLY | os.O_DIRECTORY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor = -1
    try:
        descriptor = os.open("/", flags)
        for component in path.parent.parts[1:]:
            ancestor = os.stat(component, dir_fd=descriptor, follow_symlinks=False)
            if stat.S_ISLNK(ancestor.st_mode):
                raise ValueError("Unix socket path must not contain a symlink")
            if (
                not stat.S_ISDIR(ancestor.st_mode)
                or ancestor.st_uid not in {0, os.getuid()}
                or stat.S_IMODE(ancestor.st_mode) & 0o022
            ):
                raise ValueError("Unix socket ancestor is not safely owned")
            next_descriptor = os.open(component, flags, dir_fd=descriptor)
            opened = os.fstat(next_descriptor)
            if (opened.st_dev, opened.st_ino) != (ancestor.st_dev, ancestor.st_ino):
                os.close(next_descriptor)
                raise ValueError("Unix socket ancestor identity changed")
            os.close(descriptor)
            descriptor = next_descriptor
        descriptor_parent = os.fstat(descriptor)
        if (
            descriptor_parent.st_uid != os.getuid()
            or stat.S_IMODE(descriptor_parent.st_mode) & 0o077
        ):
            raise ValueError("Unix socket boundary must be owner-private")
        descriptor_socket = os.stat(path.name, dir_fd=descriptor, follow_symlinks=False)
        if stat.S_ISLNK(descriptor_socket.st_mode):
            raise ValueError("Unix socket path must not contain a symlink")
        if (
            not stat.S_ISSOCK(descriptor_socket.st_mode)
            or descriptor_socket.st_uid != os.getuid()
            or stat.S_IMODE(descriptor_socket.st_mode) & 0o022
        ):
            raise ValueError("Unix socket boundary must be owner-private")
    except OSError as error:
        raise ValueError("Unix socket boundary is unavailable") from error
    finally:
        if descriptor >= 0:
            os.close(descriptor)
    return str(path)


class NetworkPolicy:
    __slots__ = ("_loopback_origins", "_remote_origins", "_unix_socket_paths", "profile")

    def __init__(
        self,
        *,
        profile: RuntimeProfile,
        remote_origins: Iterable[str],
        loopback_origins: Iterable[str],
        unix_socket_paths: Iterable[Path],
    ) -> None:
        if not isinstance(profile, RuntimeProfile):
            raise ValueError("invalid RSI Atlas runtime profile")
        self.profile = profile
        self._remote_origins = _canonical_unique_origins(
            remote_origins,
            canonicalizer=canonical_remote_origin,
            kind="remote origin",
        )
        self._loopback_origins = _canonical_unique_origins(
            loopback_origins,
            canonicalizer=_canonical_loopback_origin,
            kind="loopback origin",
        )
        if isinstance(unix_socket_paths, (str, bytes, Path)):
            raise ValueError("Unix socket path collection is invalid")
        sockets: set[str] = set()
        for path in unix_socket_paths:
            canonical = _validate_unix_socket(path)
            if canonical in sockets:
                raise ValueError("duplicate Unix socket path")
            sockets.add(canonical)
        self._unix_socket_paths = frozenset(sockets)

    @classmethod
    def offline(
        cls,
        *,
        loopback_origins: Iterable[str] = (),
        unix_socket_paths: Iterable[Path] = (),
    ) -> NetworkPolicy:
        return cls(
            profile=RuntimeProfile.OFFLINE,
            remote_origins=(),
            loopback_origins=loopback_origins,
            unix_socket_paths=unix_socket_paths,
        )

    @classmethod
    def monitored(
        cls,
        *,
        allowlisted_origins: Iterable[str],
        loopback_origins: Iterable[str] = (),
        unix_socket_paths: Iterable[Path] = (),
    ) -> NetworkPolicy:
        return cls(
            profile=RuntimeProfile.MONITORED,
            remote_origins=allowlisted_origins,
            loopback_origins=loopback_origins,
            unix_socket_paths=unix_socket_paths,
        )

    def _decision(
        self,
        *,
        role: ProcessRole,
        allowed: bool,
        reason: str,
        destination: str | None,
    ) -> NetworkDecision:
        return NetworkDecision(
            allowed=allowed,
            reason=reason,
            canonical_destination=destination,
            profile=self.profile,
            role=role,
        )

    def authorize(
        self,
        *,
        role: ProcessRole | str,
        scheme: str | None = None,
        host: str | None = None,
        port: int | None = None,
        unix_socket_path: Path | None = None,
    ) -> NetworkDecision:
        process_role = _parse_role(role)
        if unix_socket_path is not None:
            if scheme is not None or host is not None or port is not None:
                return self._decision(
                    role=process_role,
                    allowed=False,
                    reason="invalid_destination",
                    destination=None,
                )
            rendered = str(unix_socket_path)
            if rendered not in self._unix_socket_paths:
                return self._decision(
                    role=process_role,
                    allowed=False,
                    reason="unix_socket_not_allowlisted",
                    destination=rendered if unix_socket_path.is_absolute() else None,
                )
            try:
                canonical = _validate_unix_socket(unix_socket_path)
            except ValueError:
                return self._decision(
                    role=process_role,
                    allowed=False,
                    reason="unix_socket_boundary_invalid",
                    destination=None,
                )
            return self._decision(
                role=process_role,
                allowed=True,
                reason="approved_local_unix_socket",
                destination=canonical,
            )
        if scheme is None or host is None or port is None:
            return self._decision(
                role=process_role,
                allowed=False,
                reason="invalid_destination",
                destination=None,
            )
        try:
            address = ipaddress.ip_address(host)
        except ValueError:
            address = None
        if address is not None and address.is_loopback:
            try:
                destination = _canonical_loopback_components(scheme=scheme, host=host, port=port)
            except ValueError:
                return self._decision(
                    role=process_role,
                    allowed=False,
                    reason="invalid_destination",
                    destination=None,
                )
            allowed = destination in self._loopback_origins
            return self._decision(
                role=process_role,
                allowed=allowed,
                reason=(
                    "approved_local_loopback_origin"
                    if allowed
                    else "local_loopback_origin_not_allowlisted"
                ),
                destination=destination,
            )
        try:
            destination = _canonical_remote_components(scheme=scheme, host=host, port=port)
        except ValueError:
            return self._decision(
                role=process_role,
                allowed=False,
                reason="invalid_destination",
                destination=None,
            )
        if self.profile is RuntimeProfile.OFFLINE:
            return self._decision(
                role=process_role,
                allowed=False,
                reason="offline_profile_denies_remote_network",
                destination=destination,
            )
        if process_role is not ProcessRole.COLLECTOR:
            return self._decision(
                role=process_role,
                allowed=False,
                reason="role_has_no_remote_network_capability",
                destination=destination,
            )
        allowed = destination in self._remote_origins
        return self._decision(
            role=process_role,
            allowed=allowed,
            reason=("allowlisted_remote_origin" if allowed else "remote_origin_not_allowlisted"),
            destination=destination,
        )
