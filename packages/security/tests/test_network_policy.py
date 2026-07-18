from __future__ import annotations

import socket
import tempfile
from collections.abc import Iterator
from contextlib import closing
from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest
from rsi_atlas_security import (
    NetworkDecision,
    NetworkPolicy,
    ProcessRole,
    RuntimeProfile,
)

NON_COLLECTOR_ROLES = tuple(role for role in ProcessRole if role is not ProcessRole.COLLECTOR)


@pytest.fixture
def short_socket_root() -> Iterator[Path]:
    with tempfile.TemporaryDirectory(prefix="as-", dir=tempfile.gettempdir()) as root:
        path = Path(root).resolve()
        path.chmod(0o700)
        yield path


def test_runtime_profiles_and_process_roles_are_closed() -> None:
    assert {profile.value for profile in RuntimeProfile} == {"offline", "monitored"}
    assert {role.value for role in ProcessRole} == {
        "atlas-api",
        "atlas-engine",
        "atlas-worker-document",
        "atlas-worker-model",
        "atlas-worker-data",
        "atlas-worker-evaluation",
        "atlas-collector",
        "atlas-exporter",
        "atlas-codex-controller",
    }
    with pytest.raises(ValueError):
        ProcessRole("unknown")


@pytest.mark.parametrize("profile", ["offline", "monitored", "unknown", object()])
def test_direct_policy_constructor_rejects_mistyped_or_unknown_profile(profile: object) -> None:
    with pytest.raises(ValueError, match="runtime profile"):
        NetworkPolicy(
            profile=profile,  # type: ignore[arg-type]
            remote_origins=(),
            loopback_origins=(),
            unix_socket_paths=(),
        )


def test_network_decision_is_frozen_and_carries_policy_identity() -> None:
    decision = NetworkPolicy.offline().authorize(
        role=ProcessRole.API,
        scheme="https",
        host="example.com",
        port=443,
    )

    assert decision == NetworkDecision(
        allowed=False,
        reason="offline_profile_denies_remote_network",
        canonical_destination="https://example.com:443",
        profile=RuntimeProfile.OFFLINE,
        role=ProcessRole.API,
    )
    with pytest.raises(FrozenInstanceError):
        decision.allowed = True  # type: ignore[misc]


@pytest.mark.parametrize("role", NON_COLLECTOR_ROLES)
@pytest.mark.parametrize("profile", [RuntimeProfile.OFFLINE, RuntimeProfile.MONITORED])
def test_non_collector_roles_cannot_open_remote_destinations(
    role: ProcessRole,
    profile: RuntimeProfile,
) -> None:
    policy = (
        NetworkPolicy.offline()
        if profile is RuntimeProfile.OFFLINE
        else NetworkPolicy.monitored(allowlisted_origins=["https://rpc.example:443"])
    )

    decision = policy.authorize(
        role=role,
        scheme="https",
        host="rpc.example",
        port=443,
    )

    assert decision.allowed is False
    assert decision.reason == (
        "offline_profile_denies_remote_network"
        if profile is RuntimeProfile.OFFLINE
        else "role_has_no_remote_network_capability"
    )


def test_offline_collector_cannot_open_remote_destination() -> None:
    decision = NetworkPolicy.offline().authorize(
        role=ProcessRole.COLLECTOR,
        scheme="https",
        host="rpc.example",
        port=443,
    )

    assert decision.allowed is False
    assert decision.reason == "offline_profile_denies_remote_network"


def test_monitored_collector_requires_exact_canonical_allowlist_match() -> None:
    policy = NetworkPolicy.monitored(allowlisted_origins=["HTTPS://RPC.Example:443"])

    allowed = policy.authorize(
        role="atlas-collector",
        scheme="HTTPS",
        host="RPC.EXAMPLE",
        port=443,
    )
    suffix = policy.authorize(
        role="atlas-collector",
        scheme="https",
        host="rpc.example.evil",
        port=443,
    )
    wrong_port = policy.authorize(
        role="atlas-collector",
        scheme="https",
        host="rpc.example",
        port=8443,
    )

    assert allowed.allowed is True
    assert allowed.reason == "allowlisted_remote_origin"
    assert allowed.canonical_destination == "https://rpc.example:443"
    assert suffix.reason == "remote_origin_not_allowlisted"
    assert wrong_port.reason == "remote_origin_not_allowlisted"


@pytest.mark.parametrize(
    "origin",
    [
        "https://*.example.com:443",
        "https://.example.com:443",
        "https://user@example.com:443",
        "https://example.com/path:443",
        "https://example.com:443/path",
        "https://example.com:443?query=yes",
        "https://example.com:443#fragment",
        "https://example.com",
        "https://exämple.com:443",
        "https://example.com.:443",
        "https://127.0.0.1:443",
        "https://127.0.0.999:443",
        "https://[::1]:443",
        "http://example.com:80",
        "ftp://example.com:21",
        "https://example.com:0",
        "https://example.com:65536",
        "https://exa_mple.com:443",
        "https://example..com:443",
    ],
)
def test_monitored_policy_rejects_ambiguous_or_bypass_origins(origin: str) -> None:
    with pytest.raises(ValueError, match="remote origin"):
        NetworkPolicy.monitored(allowlisted_origins=[origin])


def test_monitored_policy_rejects_canonical_duplicate_origins() -> None:
    with pytest.raises(ValueError, match="duplicate"):
        NetworkPolicy.monitored(
            allowlisted_origins=[
                "https://RPC.EXAMPLE:443",
                "HTTPS://rpc.example:443",
            ]
        )


def test_invalid_authorization_destination_fails_closed_without_echo() -> None:
    decision = NetworkPolicy.monitored(allowlisted_origins=["https://rpc.example:443"]).authorize(
        role=ProcessRole.COLLECTOR,
        scheme="https",
        host="rpc.example.",
        port=443,
    )

    assert decision.allowed is False
    assert decision.reason == "invalid_destination"
    assert decision.canonical_destination is None


def test_unknown_role_is_rejected_instead_of_treated_as_unprivileged() -> None:
    with pytest.raises(ValueError, match="process role"):
        NetworkPolicy.offline().authorize(
            role="unknown-role",
            scheme="https",
            host="example.com",
            port=443,
        )


def test_loopback_requires_an_explicit_literal_allowlist_match() -> None:
    policy = NetworkPolicy.offline(loopback_origins=["http://127.0.0.1:8765"])

    allowed = policy.authorize(
        role=ProcessRole.API,
        scheme="http",
        host="127.0.0.1",
        port=8765,
    )
    denied = policy.authorize(
        role=ProcessRole.API,
        scheme="http",
        host="127.0.0.1",
        port=8766,
    )

    assert allowed.allowed is True
    assert allowed.reason == "approved_local_loopback_origin"
    assert denied.allowed is False
    assert denied.reason == "local_loopback_origin_not_allowlisted"


@pytest.mark.parametrize(
    "origin",
    [
        "http://localhost:8765",
        "http://0.0.0.0:8765",
        "http://192.168.1.2:8765",
        "http://127.0.0.999:8765",
        "http://127.0.0.1",
        "http://127.0.0.1:8765/path",
    ],
)
def test_loopback_configuration_rejects_aliases_and_nonliteral_destinations(
    origin: str,
) -> None:
    with pytest.raises(ValueError, match="loopback origin"):
        NetworkPolicy.offline(loopback_origins=[origin])


def test_owner_private_unix_socket_requires_an_exact_match(short_socket_root: Path) -> None:
    socket_path = short_socket_root / "atlas.sock"
    with closing(socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)) as server:
        server.bind(str(socket_path))
        socket_path.chmod(0o600)
        policy = NetworkPolicy.offline(unix_socket_paths=[socket_path])

        allowed = policy.authorize(
            role=ProcessRole.ENGINE,
            unix_socket_path=socket_path,
        )
        denied = policy.authorize(
            role=ProcessRole.ENGINE,
            unix_socket_path=short_socket_root / "other.sock",
        )

    assert allowed.allowed is True
    assert allowed.reason == "approved_local_unix_socket"
    assert allowed.canonical_destination == str(socket_path)
    assert denied.allowed is False
    assert denied.reason == "unix_socket_not_allowlisted"


def test_unix_socket_configuration_rejects_relative_symlink_and_unsafe_mode(
    short_socket_root: Path,
) -> None:
    socket_path = short_socket_root / "atlas.sock"
    with closing(socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)) as server:
        server.bind(str(socket_path))
        socket_path.chmod(0o666)
        with pytest.raises(ValueError, match="owner-private"):
            NetworkPolicy.offline(unix_socket_paths=[socket_path])

        socket_path.chmod(0o600)
        alias = short_socket_root / "alias.sock"
        alias.symlink_to(socket_path)
        with pytest.raises(ValueError, match="symlink"):
            NetworkPolicy.offline(unix_socket_paths=[alias])

        with pytest.raises(ValueError, match="absolute"):
            NetworkPolicy.offline(unix_socket_paths=[Path("relative.sock")])

        with pytest.raises(ValueError, match="unavailable"):
            NetworkPolicy.offline(unix_socket_paths=[short_socket_root / "missing.sock"])


def test_unix_socket_configuration_rejects_unsafe_or_symlinked_ancestor(
    short_socket_root: Path,
) -> None:
    unsafe = short_socket_root / "unsafe"
    unsafe.mkdir(mode=0o700)
    private = unsafe / "private"
    private.mkdir(mode=0o700)
    socket_path = private / "atlas.sock"
    with closing(socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)) as server:
        server.bind(str(socket_path))
        socket_path.chmod(0o600)
        unsafe.chmod(0o777)
        with pytest.raises(ValueError, match="ancestor"):
            NetworkPolicy.offline(unix_socket_paths=[socket_path])
        unsafe.chmod(0o700)

        linked = short_socket_root / "linked"
        linked.symlink_to(unsafe, target_is_directory=True)
        with pytest.raises(ValueError, match="symlink"):
            NetworkPolicy.offline(unix_socket_paths=[linked / "private" / "atlas.sock"])
