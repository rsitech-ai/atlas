#!/usr/bin/env python3
"""Start the RSI Atlas engine on release IPC (UDS) or explicit loopback TCP."""

from __future__ import annotations

import argparse
import os
import sys

import uvicorn
from rsi_atlas_engine.runtime import RuntimePaths
from rsi_atlas_security.ipc import (
    IpcTransportMode,
    assert_no_unintended_tcp,
    ensure_ipc_token,
    prepare_uds_path,
    resolve_ipc_bind,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--allow-loopback-tcp",
        action="store_true",
        help="Enable 127.0.0.1 TCP (tests/dev only; forbidden with --release-ipc).",
    )
    parser.add_argument(
        "--release-ipc",
        action="store_true",
        help="Force release Unix-domain socket mode (criterion 114).",
    )
    parser.add_argument("--rotate-token", action="store_true")
    args = parser.parse_args(argv)

    if args.release_ipc:
        os.environ["RSI_ATLAS_RELEASE_IPC"] = "1"
        os.environ.pop("RSI_ATLAS_ALLOW_LOOPBACK_TCP", None)
    elif args.allow_loopback_tcp:
        os.environ["RSI_ATLAS_ALLOW_LOOPBACK_TCP"] = "1"
    # Default without flags: UDS (safer). Dev Swift path sets ALLOW_LOOPBACK_TCP via build_and_run.

    os.environ.setdefault("RSI_ATLAS_IPC_AUTH", "1")
    paths = RuntimePaths.from_environment()
    cfg = resolve_ipc_bind(data_root=paths.data_root)
    assert_no_unintended_tcp(release_mode=cfg.release_mode, mode=cfg.mode)
    token = ensure_ipc_token(cfg.token_path, rotate=args.rotate_token)
    print(f"ipc_mode={cfg.mode.value}", flush=True)
    print(f"ipc_token_path={cfg.token_path}", flush=True)
    # Do not print the token value.

    if cfg.mode is IpcTransportMode.UNIX_DOMAIN:
        assert cfg.uds_path is not None
        uds = prepare_uds_path(cfg.uds_path)
        print(f"ipc_uds={uds}", flush=True)
        uvicorn.run(
            "rsi_atlas_engine.api:app",
            uds=str(uds),
            factory=False,
            log_level="info",
        )
    else:
        assert cfg.host is not None and cfg.port is not None
        print(f"ipc_tcp={cfg.host}:{cfg.port}", flush=True)
        print(
            "note: loopback TCP is development/test only; release uses Unix domain sockets.",
            flush=True,
        )
        del token  # token file still required when RSI_ATLAS_IPC_AUTH=1
        uvicorn.run(
            "rsi_atlas_engine.api:app",
            host=cfg.host,
            port=cfg.port,
            factory=False,
            log_level="info",
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
