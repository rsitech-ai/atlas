import argparse
import sys
from collections.abc import Callable, Sequence
from typing import NoReturn, TextIO

from rsi_atlas_contracts import HealthState, SystemStatus

from rsi_atlas_engine.runtime import RuntimeServices


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="atlas", description="RSI Atlas local tooling")
    commands = parser.add_subparsers(dest="command", required=True)
    doctor = commands.add_parser("doctor", help="Inspect the local RSI Atlas runtime")
    doctor.add_argument("--json", action="store_true", help="Emit the versioned JSON contract")
    return parser


def main(
    argv: Sequence[str] | None = None,
    *,
    stdout: TextIO = sys.stdout,
    status_factory: Callable[[], SystemStatus] | None = None,
) -> int:
    args = build_parser().parse_args(argv)
    status = (status_factory or RuntimeServices.from_environment().status)()

    if args.json:
        print(status.model_dump_json(indent=2), file=stdout)
    else:
        print(f"RSI Atlas: {status.state.value} ({status.profile.value})", file=stdout)
        for component in status.components:
            print(
                f"- {component.title}: {component.state.value} — {component.summary}",
                file=stdout,
            )
            if component.remediation is not None:
                print(f"  Remediation: {component.remediation}", file=stdout)

    return 0 if status.state in {HealthState.HEALTHY, HealthState.DEGRADED} else 1


def entrypoint() -> NoReturn:
    raise SystemExit(main())
