"""Authenticated local IPC transport policy (Unix domain socket vs loopback TCP)."""

from __future__ import annotations

import os
import secrets
import stat
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path


class IpcTransportMode(StrEnum):
    UNIX_DOMAIN = "unix_domain"
    LOOPBACK_TCP = "loopback_tcp"


class IpcTransportError(RuntimeError):
    """Raised when release IPC policy is violated."""


@dataclass(frozen=True, slots=True)
class IpcBindConfig:
    mode: IpcTransportMode
    uds_path: Path | None
    host: str | None
    port: int | None
    token_path: Path
    release_mode: bool


def _truthy(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in {"1", "true", "yes", "on"}


def resolve_ipc_bind(*, data_root: Path) -> IpcBindConfig:
    """Resolve bind target.

    Release IPC (default when ``RSI_ATLAS_RELEASE_IPC=1``): Unix domain socket only.
    Loopback TCP requires explicit ``RSI_ATLAS_ALLOW_LOOPBACK_TCP=1`` and is forbidden
    in release mode (criterion 114).
    """
    ipc_dir = data_root / "ipc"
    token_path = ipc_dir / "engine.token"
    uds_path = ipc_dir / "engine.sock"
    release_mode = _truthy("RSI_ATLAS_RELEASE_IPC")
    allow_tcp = _truthy("RSI_ATLAS_ALLOW_LOOPBACK_TCP")
    if release_mode and allow_tcp:
        raise IpcTransportError(
            "release IPC forbids loopback TCP; unset RSI_ATLAS_ALLOW_LOOPBACK_TCP"
        )
    if release_mode or not allow_tcp:
        return IpcBindConfig(
            mode=IpcTransportMode.UNIX_DOMAIN,
            uds_path=uds_path,
            host=None,
            port=None,
            token_path=token_path,
            release_mode=release_mode,
        )
    host = os.environ.get("RSI_ATLAS_ENGINE_HOST", "127.0.0.1").strip() or "127.0.0.1"
    if host not in {"127.0.0.1", "::1", "localhost"}:
        raise IpcTransportError("loopback TCP host must be 127.0.0.1, ::1, or localhost")
    port = int(os.environ.get("RSI_ATLAS_ENGINE_PORT", "8765"))
    if not (1 <= port <= 65535):
        raise IpcTransportError("engine port out of range")
    return IpcBindConfig(
        mode=IpcTransportMode.LOOPBACK_TCP,
        uds_path=None,
        host=host,
        port=port,
        token_path=token_path,
        release_mode=False,
    )


def ensure_owner_private_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    path.chmod(stat.S_IRWXU)  # 0700


def ensure_ipc_token(token_path: Path, *, rotate: bool = False) -> str:
    """Create or load an owner-private shared token for local IPC auth."""
    ensure_owner_private_dir(token_path.parent)
    if token_path.is_file() and not rotate:
        token = token_path.read_text(encoding="utf-8").strip()
        if len(token) >= 32:
            return token
    token = secrets.token_urlsafe(32)
    token_path.write_text(token + "\n", encoding="utf-8")
    token_path.chmod(stat.S_IRUSR | stat.S_IWUSR)  # 0600
    return token


def prepare_uds_path(uds_path: Path) -> Path:
    ensure_owner_private_dir(uds_path.parent)
    if uds_path.exists():
        uds_path.unlink()
    return uds_path


def load_ipc_token(token_path: Path) -> str | None:
    if not token_path.is_file():
        return None
    token = token_path.read_text(encoding="utf-8").strip()
    return token if token else None


def tokens_match(*, provided: str | None, expected: str | None) -> bool:
    if not expected or not provided:
        return False
    return secrets.compare_digest(provided.strip(), expected.strip())


def assert_no_unintended_tcp(*, release_mode: bool, mode: IpcTransportMode) -> None:
    if release_mode and mode is not IpcTransportMode.UNIX_DOMAIN:
        raise IpcTransportError("criterion 114: release must not expose a TCP API")


__all__ = [
    "IpcBindConfig",
    "IpcTransportError",
    "IpcTransportMode",
    "assert_no_unintended_tcp",
    "ensure_ipc_token",
    "ensure_owner_private_dir",
    "load_ipc_token",
    "prepare_uds_path",
    "resolve_ipc_bind",
    "tokens_match",
]
