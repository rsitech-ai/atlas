"""Build helpers for the self-contained macOS release runtime."""

from __future__ import annotations

import hashlib
import json
import os
import platform
import shutil
import subprocess
import sys
import tempfile
import urllib.request
from dataclasses import dataclass
from pathlib import Path

from rsi_atlas_release.assembly import validate_runtime_payload

_PYTHON_VERSION = "3.12.10"
_POSTGRESQL_VERSION = "17.10"
_PGVECTOR_VERSION = "0.8.5"
_CPYTHON_LICENSE_URL = "https://raw.githubusercontent.com/python/cpython/v3.12.10/LICENSE"
_CPYTHON_LICENSE_SHA256 = "3b2f81fe21d181c499c59a256c8e1968455d6689d269aa85373bfb6af41da3bf"


@dataclass(frozen=True, slots=True)
class RuntimeBuildInputs:
    repo_root: Path
    python_prefix: Path
    postgresql_prefix: Path
    pgvector_prefix: Path

    @classmethod
    def local(cls, repo_root: Path) -> RuntimeBuildInputs:
        return cls(
            repo_root=repo_root.resolve(strict=True),
            python_prefix=Path(sys.base_prefix).resolve(strict=True),
            postgresql_prefix=Path("/opt/homebrew/opt/postgresql@17").resolve(strict=True),
            pgvector_prefix=Path("/opt/homebrew/opt/pgvector").resolve(strict=True),
        )


def _run(
    arguments: list[str],
    *,
    cwd: Path | None = None,
    input_text: str | None = None,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        arguments,
        cwd=cwd,
        check=True,
        capture_output=True,
        text=True,
        input=input_text,
    )


def _tree_sha256(root: Path) -> str:
    digest = hashlib.sha256()
    for candidate in sorted(root.rglob("*")):
        relative = candidate.relative_to(root).as_posix().encode("utf-8")
        digest.update(len(relative).to_bytes(8, "big"))
        digest.update(relative)
        if candidate.is_symlink():
            payload = os.readlink(candidate).encode("utf-8")
            kind = b"L"
        elif candidate.is_dir():
            payload = b""
            kind = b"D"
        elif candidate.is_file():
            payload = candidate.read_bytes()
            kind = b"F"
        else:
            raise ValueError("runtime build input contains a special file")
        digest.update(kind)
        digest.update(len(payload).to_bytes(8, "big"))
        digest.update(payload)
    return digest.hexdigest()


def _validate_materializable_tree(root: Path) -> None:
    resolved_root = root.resolve(strict=True)
    for candidate in root.rglob("*"):
        if candidate.is_symlink():
            try:
                candidate.resolve(strict=True).relative_to(resolved_root)
            except (FileNotFoundError, RuntimeError, ValueError) as error:
                raise ValueError("runtime build input contains an unsafe symlink") from error
            continue
        mode = candidate.lstat().st_mode
        if not (candidate.is_file() or candidate.is_dir()):
            raise ValueError("runtime build input contains a special file")
        if mode & 0o002:
            raise ValueError("runtime build input is world-writable")


def _copy_materialized_tree(source: Path, destination: Path) -> None:
    _validate_materializable_tree(source)
    shutil.copytree(source, destination, symlinks=False)


def _git_provenance(repo_root: Path, *, require_clean: bool) -> dict[str, str]:
    status = _run(
        ["git", "status", "--porcelain", "--untracked-files=normal"],
        cwd=repo_root,
    ).stdout
    if require_clean and status:
        raise ValueError("release runtime requires a clean Git worktree")
    return {
        "commit": _run(["git", "rev-parse", "HEAD"], cwd=repo_root).stdout.strip(),
        "tree": _run(["git", "rev-parse", "HEAD^{tree}"], cwd=repo_root).stdout.strip(),
        "worktree": "clean" if not status else "dirty-development",
    }


def _validate_versions(inputs: RuntimeBuildInputs) -> None:
    if platform.machine() != "arm64":
        raise ValueError("release runtime requires an Apple Silicon host")
    python = inputs.python_prefix / "bin" / "python3.12"
    postgres = inputs.postgresql_prefix / "bin" / "postgres"
    python_version = _run([str(python), "--version"]).stdout.strip()
    postgres_version = _run([str(postgres), "--version"]).stdout.strip()
    receipt = json.loads((inputs.pgvector_prefix / "INSTALL_RECEIPT.json").read_text())
    pgvector_version = receipt["source"]["versions"]["stable"]
    if python_version != f"Python {_PYTHON_VERSION}":
        raise ValueError("unexpected CPython build input version")
    if postgres_version != f"postgres (PostgreSQL) {_POSTGRESQL_VERSION} (Homebrew)":
        raise ValueError("unexpected PostgreSQL build input version")
    if pgvector_version != _PGVECTOR_VERSION:
        raise ValueError("unexpected pgvector build input version")


def _copy_cpython(inputs: RuntimeBuildInputs, payload: Path) -> None:
    source = inputs.python_prefix
    destination = payload / "Contents" / "Resources" / "runtime" / "python"
    (destination / "bin").mkdir(parents=True)
    (destination / "lib").mkdir()
    shutil.copy2(source / "bin" / "python3.12", destination / "bin" / "python3")
    shutil.copy2(source / "lib" / "libpython3.12.dylib", destination / "lib")

    def ignore(directory: str, names: list[str]) -> set[str]:
        ignored = {"__pycache__", "ensurepip", "idlelib", "site-packages", "test", "tests"}
        return ignored.intersection(names)

    shutil.copytree(
        source / "lib" / "python3.12",
        destination / "lib" / "python3.12",
        symlinks=False,
        ignore=ignore,
    )
    (destination / "lib" / "python3.12" / "site-packages").mkdir()


def _install_python_packages(
    inputs: RuntimeBuildInputs,
    payload: Path,
    build_root: Path,
) -> list[str]:
    site_packages = (
        payload
        / "Contents"
        / "Resources"
        / "runtime"
        / "python"
        / "lib"
        / "python3.12"
        / "site-packages"
    )
    requirements = _run(
        [
            "uv",
            "export",
            "--frozen",
            "--no-dev",
            "--no-emit-workspace",
            "--format",
            "requirements-txt",
        ],
        cwd=inputs.repo_root,
    ).stdout
    _run(
        [
            "uv",
            "pip",
            "install",
            "--python",
            str(inputs.python_prefix / "bin" / "python3.12"),
            "--target",
            str(site_packages),
            "--no-compile",
            "--require-hashes",
            "--requirements",
            "-",
        ],
        cwd=inputs.repo_root,
        input_text=requirements,
    )
    wheel_root = build_root / "workspace-wheels"
    wheel_root.mkdir()
    _run(
        ["uv", "build", "--all-packages", "--wheel", "--out-dir", str(wheel_root)],
        cwd=inputs.repo_root,
    )
    wheels = sorted(wheel_root.glob("*.whl"))
    if len(wheels) != 16:
        raise ValueError("workspace wheel set is incomplete")
    _run(
        [
            "uv",
            "pip",
            "install",
            "--python",
            str(inputs.python_prefix / "bin" / "python3.12"),
            "--target",
            str(site_packages),
            "--no-deps",
            "--no-compile",
            *(str(wheel) for wheel in wheels),
        ],
        cwd=inputs.repo_root,
    )
    for candidate in site_packages.rglob("direct_url.json"):
        candidate.unlink()
    shutil.rmtree(site_packages / "bin", ignore_errors=True)
    return [f"{wheel.name}:{hashlib.sha256(wheel.read_bytes()).hexdigest()}" for wheel in wheels]


def _copy_postgresql(inputs: RuntimeBuildInputs, payload: Path) -> None:
    destination = payload / "Contents" / "Resources" / "runtime" / "postgresql"
    _copy_materialized_tree(inputs.postgresql_prefix, destination)
    vector = inputs.pgvector_prefix / "lib" / "postgresql@17" / "vector.dylib"
    vector_destination = destination / "lib" / "postgresql" / "vector.dylib"
    vector_destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(vector, vector_destination)
    shutil.copytree(
        inputs.pgvector_prefix / "share" / "postgresql@17" / "extension",
        destination / "share" / "postgresql@17" / "extension",
        dirs_exist_ok=True,
    )


def _download_cpython_license(destination: Path) -> None:
    with urllib.request.urlopen(_CPYTHON_LICENSE_URL, timeout=30) as response:
        payload = response.read()
    if hashlib.sha256(payload).hexdigest() != _CPYTHON_LICENSE_SHA256:
        raise ValueError("CPython license hash mismatch")
    destination.write_bytes(payload)


def _copy_legal(inputs: RuntimeBuildInputs, payload: Path) -> None:
    legal = payload / "Contents" / "Resources" / "Legal" / "third-party"
    legal.mkdir(parents=True)
    _download_cpython_license(legal / "CPython-LICENSE.txt")
    shutil.copy2(
        inputs.postgresql_prefix / "COPYRIGHT",
        legal / "PostgreSQL-COPYRIGHT.txt",
    )
    shutil.copy2(inputs.pgvector_prefix / "LICENSE", legal / "pgvector-LICENSE.txt")


def build_runtime_payload(
    *,
    inputs: RuntimeBuildInputs,
    destination: Path,
    launcher_source: Path,
    require_clean_git: bool = True,
) -> Path:
    """Build a production-only runtime payload atomically from recorded local inputs."""
    _validate_versions(inputs)
    for source_root in (
        inputs.python_prefix,
        inputs.postgresql_prefix,
        inputs.pgvector_prefix,
    ):
        _validate_materializable_tree(source_root)
    git = _git_provenance(inputs.repo_root, require_clean=require_clean_git)
    destination.parent.mkdir(parents=True, exist_ok=True)
    build_root = Path(
        tempfile.mkdtemp(prefix=f".{destination.name}.build-", dir=destination.parent)
    )
    payload = build_root / destination.name
    previous = build_root / f".{destination.name}.previous"
    moved_previous = False
    try:
        _copy_cpython(inputs, payload)
        wheel_hashes = _install_python_packages(inputs, payload, build_root)
        _copy_postgresql(inputs, payload)
        _copy_legal(inputs, payload)
        compile_engine_launcher(
            source=launcher_source,
            destination=payload / "Contents" / "MacOS" / "RSIAtlasEngine",
        )
        provenance = {
            "git": git,
            "pgvector": {
                "receipt_sha256": hashlib.sha256(
                    (inputs.pgvector_prefix / "INSTALL_RECEIPT.json").read_bytes()
                ).hexdigest(),
                "source_tree_sha256": _tree_sha256(inputs.pgvector_prefix),
                "version": _PGVECTOR_VERSION,
            },
            "postgresql": {
                "receipt_sha256": hashlib.sha256(
                    (inputs.postgresql_prefix / "INSTALL_RECEIPT.json").read_bytes()
                ).hexdigest(),
                "source_tree_sha256": _tree_sha256(inputs.postgresql_prefix),
                "version": _POSTGRESQL_VERSION,
            },
            "python": {
                "source_tree_sha256": _tree_sha256(inputs.python_prefix),
                "version": _PYTHON_VERSION,
            },
            "schema_version": "rsi-atlas.runtime-build-inputs.v1",
            "workspace_wheels": wheel_hashes,
        }
        provenance_path = payload / "Contents" / "Resources" / "runtime-build-inputs.json"
        provenance_path.write_text(
            json.dumps(provenance, sort_keys=True, separators=(",", ":")) + "\n",
            encoding="utf-8",
        )
        validate_runtime_payload(payload)
        if os.path.lexists(destination):
            os.replace(destination, previous)
            moved_previous = True
        os.replace(payload, destination)
    except Exception:
        if moved_previous and not os.path.lexists(destination):
            os.replace(previous, destination)
        raise
    finally:
        shutil.rmtree(build_root, ignore_errors=True)
    return destination


def compile_engine_launcher(
    *,
    source: Path,
    destination: Path,
    compiler: Path = Path("/usr/bin/clang"),
) -> Path:
    """Compile the minimal bundle-relative ARM64 launcher and replace atomically."""
    if source.is_symlink() or not source.is_file() or source.stat().st_size == 0:
        raise ValueError("engine launcher source must be a non-empty regular file")
    if not compiler.is_file() or not os.access(compiler, os.X_OK):
        raise ValueError("Apple clang is unavailable")
    destination.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{destination.name}.",
        dir=destination.parent,
    )
    os.close(descriptor)
    temporary = Path(temporary_name)
    try:
        subprocess.run(
            [
                str(compiler),
                "-arch",
                "arm64",
                "-mmacosx-version-min=15.0",
                "-Os",
                "-Wall",
                "-Wextra",
                "-Werror",
                str(source),
                "-o",
                str(temporary),
            ],
            check=True,
            capture_output=True,
            text=True,
        )
        temporary.chmod(0o700)
        os.replace(temporary, destination)
    finally:
        temporary.unlink(missing_ok=True)
    return destination
