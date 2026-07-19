#!/usr/bin/env python3
"""Wait for authenticated local engine IPC (UDS or loopback TCP)."""

from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

import httpx
from rsi_atlas_engine.runtime import RuntimePaths
from rsi_atlas_security.ipc import IpcTransportMode, load_ipc_token, resolve_ipc_bind


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--timeout-seconds", type=float, default=5.0)
    parser.add_argument("--require-auth", action="store_true")
    args = parser.parse_args(argv)
    paths = RuntimePaths.from_environment()
    cfg = resolve_ipc_bind(data_root=paths.data_root)
    token = load_ipc_token(cfg.token_path)
    if args.require_auth and not token:
        print("ipc token missing", file=sys.stderr)
        return 2
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    deadline = time.monotonic() + args.timeout_seconds
    last_error = "not attempted"
    while time.monotonic() < deadline:
        try:
            if cfg.mode is IpcTransportMode.UNIX_DOMAIN:
                assert cfg.uds_path is not None
                transport = httpx.HTTPTransport(uds=str(cfg.uds_path))
                with httpx.Client(transport=transport, timeout=0.5) as client:
                    response = client.get("http://localhost/v1/system/status", headers=headers)
            else:
                assert cfg.host is not None and cfg.port is not None
                with httpx.Client(timeout=0.5) as client:
                    response = client.get(
                        f"http://{cfg.host}:{cfg.port}/v1/system/status",
                        headers=headers,
                    )
            if response.status_code == 200:
                print(f"ipc_ready mode={cfg.mode.value} status={response.status_code}")
                return 0
            if response.status_code in {401, 403}:
                print(f"ipc_auth_failed status={response.status_code}", file=sys.stderr)
                return 3
            last_error = f"status={response.status_code}"
        except Exception as exc:  # readiness probe: any connect/read failure retries
            last_error = str(exc)
        time.sleep(0.1)
    print(f"ipc_not_ready: {last_error}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    # Allow unset TCP flag to resolve UDS when RSI_ATLAS_RELEASE_IPC=1.
    os.environ.setdefault("RSI_ATLAS_DATA_ROOT", str(Path.cwd() / ".local"))
    sys.exit(main())
