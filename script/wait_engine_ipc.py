#!/usr/bin/env python3
"""Wait for authenticated local engine IPC (UDS or loopback TCP)."""

from __future__ import annotations

import argparse
import os
import socket
import sys
import time
from pathlib import Path

from rsi_atlas_engine.runtime import RuntimePaths
from rsi_atlas_security.ipc import IpcTransportMode, load_ipc_token, resolve_ipc_bind


def _http_get(
    *,
    path: str,
    headers: dict[str, str],
    uds_path: Path | None = None,
    host: str | None = None,
    port: int | None = None,
) -> tuple[int, bytes]:
    """Minimal HTTP/1.1 GET over UDS or TCP (stdlib only)."""
    request_lines = [
        f"GET {path} HTTP/1.1",
        f"Host: {host or 'localhost'}",
        "Connection: close",
    ]
    for key, value in headers.items():
        request_lines.append(f"{key}: {value}")
    payload = ("\r\n".join(request_lines) + "\r\n\r\n").encode("ascii")

    if uds_path is not None:
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        sock.settimeout(0.5)
        sock.connect(str(uds_path))
    else:
        assert host is not None and port is not None
        sock = socket.create_connection((host, port), timeout=0.5)
    try:
        sock.sendall(payload)
        chunks: list[bytes] = []
        while True:
            chunk = sock.recv(65_536)
            if not chunk:
                break
            chunks.append(chunk)
            if sum(len(part) for part in chunks) > 1_048_576:
                break
    finally:
        sock.close()
    raw = b"".join(chunks)
    head, _, body = raw.partition(b"\r\n\r\n")
    status_line = head.split(b"\r\n", 1)[0].decode("ascii", errors="replace")
    parts = status_line.split(" ")
    if len(parts) < 2 or not parts[1].isdigit():
        raise RuntimeError(f"invalid status line: {status_line!r}")
    return int(parts[1]), body


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--timeout-seconds", type=float, default=5.0)
    parser.add_argument("--require-auth", action="store_true")
    args = parser.parse_args(argv)
    paths = RuntimePaths.from_environment()
    cfg = resolve_ipc_bind(data_root=paths.data_root)
    deadline = time.monotonic() + args.timeout_seconds
    last_error = "not attempted"
    while time.monotonic() < deadline:
        token = load_ipc_token(cfg.token_path)
        if args.require_auth and not token:
            last_error = "ipc token missing"
            time.sleep(0.1)
            continue
        headers = {"Authorization": f"Bearer {token}"} if token else {}
        try:
            if cfg.mode is IpcTransportMode.UNIX_DOMAIN:
                assert cfg.uds_path is not None
                status, _ = _http_get(
                    path="/v1/system/status",
                    headers=headers,
                    uds_path=cfg.uds_path,
                )
            else:
                assert cfg.host is not None and cfg.port is not None
                status, _ = _http_get(
                    path="/v1/system/status",
                    headers=headers,
                    host=cfg.host,
                    port=cfg.port,
                )
            if status == 200:
                print(f"ipc_ready mode={cfg.mode.value} status={status}")
                return 0
            if status in {401, 403}:
                print(f"ipc_auth_failed status={status}", file=sys.stderr)
                return 3
            last_error = f"status={status}"
        except Exception as exc:  # readiness probe: any connect/read failure retries
            last_error = str(exc)
        time.sleep(0.1)
    print(f"ipc_not_ready: {last_error}", file=sys.stderr)
    return 2 if args.require_auth and last_error == "ipc token missing" else 1


if __name__ == "__main__":
    os.environ.setdefault("RSI_ATLAS_DATA_ROOT", str(Path.cwd() / ".local"))
    sys.exit(main())
