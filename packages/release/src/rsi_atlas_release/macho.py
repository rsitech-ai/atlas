"""Fail-closed parsing and resolution of macOS Mach-O dependencies."""

from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

_LOAD_COMMANDS = {
    "LC_LOAD_DYLIB",
    "LC_LOAD_WEAK_DYLIB",
    "LC_REEXPORT_DYLIB",
    "LC_LOAD_UPWARD_DYLIB",
}
_SYSTEM_ROOTS = (Path("/System/Library"), Path("/usr/lib"))
_ARCHITECTURE_HEADER = re.compile(r"^.+ \(architecture ([^)]+)\):$")
_MACHO_MAGICS = {
    b"\xfe\xed\xfa\xce",
    b"\xce\xfa\xed\xfe",
    b"\xfe\xed\xfa\xcf",
    b"\xcf\xfa\xed\xfe",
    b"\xca\xfe\xba\xbe",
    b"\xbe\xba\xfe\xca",
    b"\xca\xfe\xba\xbf",
    b"\xbf\xba\xfe\xca",
}


class MachOParseError(ValueError):
    """Raised when otool output is ambiguous or structurally incomplete."""


@dataclass(frozen=True, slots=True)
class MachOLoad:
    command: str
    name: str


@dataclass(frozen=True, slots=True)
class MachOCommands:
    identifier: str | None
    loads: tuple[MachOLoad, ...]
    rpaths: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class MachOClosure:
    images: int
    loads: int
    system_loads: int
    bundled_loads: int


def _selected_architecture_lines(output: str, architecture: str) -> list[str]:
    lines: list[str] = []
    selected = True
    saw_header = False
    for line in output.splitlines():
        header = _ARCHITECTURE_HEADER.match(line.strip())
        if header:
            saw_header = True
            selected = header.group(1) == architecture
            continue
        if selected:
            lines.append(line)
    if saw_header and not lines:
        raise MachOParseError(f"otool output has no {architecture} architecture")
    return lines


def parse_otool_load_commands(output: str, *, architecture: str) -> MachOCommands:
    """Parse the LC_ID_DYLIB, dyld loads, and ordered LC_RPATH values from otool -l."""
    lines = _selected_architecture_lines(output, architecture)
    identifier: str | None = None
    loads: list[MachOLoad] = []
    rpaths: list[str] = []
    index = 0
    while index < len(lines):
        stripped = lines[index].strip()
        if not stripped.startswith("cmd LC_"):
            index += 1
            continue
        command = stripped.removeprefix("cmd ")
        if command not in _LOAD_COMMANDS | {"LC_ID_DYLIB", "LC_RPATH"}:
            index += 1
            continue
        field = "path" if command == "LC_RPATH" else "name"
        value: str | None = None
        probe = index + 1
        while probe < len(lines):
            candidate = lines[probe].strip()
            if candidate.startswith("cmd LC_") or candidate.startswith("Load command "):
                break
            prefix = f"{field} "
            if candidate.startswith(prefix):
                value = candidate[len(prefix) :].rsplit(" (offset ", 1)[0]
                break
            probe += 1
        if value is None:
            raise MachOParseError(f"{command} is missing {field}")
        if command == "LC_ID_DYLIB":
            if identifier is not None and identifier != value:
                raise MachOParseError("Mach-O image has multiple identifiers")
            identifier = value
        elif command == "LC_RPATH":
            rpaths.append(value)
        else:
            loads.append(MachOLoad(command, value))
        index = probe + 1
    return MachOCommands(identifier, tuple(loads), tuple(rpaths))


def _inside(path: Path, root: Path) -> Path:
    normalized = path.resolve(strict=False)
    try:
        normalized.relative_to(root.resolve(strict=True))
    except ValueError as error:
        raise ValueError("Mach-O dependency escapes the application bundle") from error
    return normalized


def _expand_token(
    value: str,
    *,
    loader: Path,
    executable: Path,
    bundle_root: Path,
) -> Path:
    if value == "@loader_path" or value.startswith("@loader_path/"):
        suffix = value.removeprefix("@loader_path").lstrip("/")
        return _inside(loader.parent / suffix, bundle_root)
    if value == "@executable_path" or value.startswith("@executable_path/"):
        suffix = value.removeprefix("@executable_path").lstrip("/")
        return _inside(executable.parent / suffix, bundle_root)
    raise ValueError("unsupported dyld path token")


def resolve_load_path(
    name: str,
    *,
    loader: Path,
    executable: Path,
    rpaths: tuple[str, ...],
    bundle_root: Path,
) -> Path | None:
    """Resolve a load command to an in-bundle file, or None for an Apple system file."""
    if name.startswith("/"):
        absolute = Path(name)
        if any(absolute == root or absolute.is_relative_to(root) for root in _SYSTEM_ROOTS):
            return None
        raise ValueError(f"non-system absolute dependency: {name}")
    if name.startswith("@loader_path") or name.startswith("@executable_path"):
        resolved = _expand_token(
            name,
            loader=loader,
            executable=executable,
            bundle_root=bundle_root,
        )
        if not resolved.is_file():
            raise ValueError(f"unresolved dyld dependency: {name}")
        return resolved
    if name.startswith("@rpath/"):
        suffix = name.removeprefix("@rpath/")
        for rpath in rpaths:
            try:
                base = _expand_token(
                    rpath,
                    loader=loader,
                    executable=executable,
                    bundle_root=bundle_root,
                )
            except ValueError:
                continue
            candidate = _inside(base / suffix, bundle_root)
            if candidate.is_file():
                return candidate
        raise ValueError(f"unresolved @rpath dependency: {name}")
    raise ValueError(f"unsupported Mach-O dependency: {name}")


def is_macho(path: Path) -> bool:
    """Return whether a regular file begins with a Mach-O or universal Mach-O magic."""
    if not path.is_file() or path.is_symlink():
        return False
    with path.open("rb") as stream:
        return stream.read(4) in _MACHO_MAGICS


def read_macho_commands(path: Path, *, architecture: str = "arm64") -> MachOCommands:
    result = subprocess.run(
        ["/usr/bin/otool", "-arch", architecture, "-l", str(path)],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise MachOParseError(f"otool could not inspect {path.name}")
    return parse_otool_load_commands(result.stdout, architecture=architecture)


def verify_macho_closure(bundle_root: Path) -> MachOClosure:
    """Recompute ARM64 dyld closure without trusting a prior manifest."""
    root = bundle_root.resolve(strict=True)
    images = loads = system_loads = bundled_loads = 0
    for image in sorted(root.rglob("*")):
        if not is_macho(image):
            continue
        images += 1
        commands = read_macho_commands(image)
        if commands.identifier is not None:
            identifier = commands.identifier
            if identifier.startswith("/"):
                raise ValueError(f"absolute Mach-O identifier: {identifier}")
            if not identifier.startswith(("@loader_path/", "@rpath/")):
                raise ValueError(f"unsupported Mach-O identifier: {identifier}")
        for rpath in commands.rpaths:
            if rpath.startswith("/"):
                raise ValueError(f"absolute Mach-O rpath in {image.name}: {rpath}")
            if not rpath.startswith(("@loader_path", "@executable_path")):
                raise ValueError(f"unsupported Mach-O rpath in {image.name}: {rpath}")
            _expand_token(
                rpath,
                loader=image,
                executable=image,
                bundle_root=root,
            )
        for load in commands.loads:
            loads += 1
            try:
                resolved = resolve_load_path(
                    load.name,
                    loader=image,
                    executable=image,
                    rpaths=commands.rpaths,
                    bundle_root=root,
                )
            except ValueError as error:
                raise ValueError(f"{image.relative_to(root)}: {error}") from error
            if resolved is None:
                system_loads += 1
            else:
                bundled_loads += 1
    return MachOClosure(images, loads, system_loads, bundled_loads)
