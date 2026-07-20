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
from rsi_atlas_release.macho import (
    is_macho,
    read_macho_commands,
    resolve_load_path,
    verify_macho_closure,
)

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


def _relative_to(path: Path, root: Path) -> Path | None:
    try:
        return path.relative_to(root)
    except ValueError:
        return None


def _copy_distinct_file(source: Path, destination: Path) -> None:
    if not source.is_file() or source.is_symlink():
        raise ValueError("native dependency must resolve to a regular file")
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        if (
            hashlib.sha256(source.read_bytes()).digest()
            != hashlib.sha256(destination.read_bytes()).digest()
        ):
            raise ValueError("native dependency destination collision")
        return
    shutil.copy2(source, destination)


def _copy_native_provider_legal(
    *,
    keg_root: Path,
    formula: str,
    payload: Path,
) -> list[str]:
    legal_root = payload / "Contents" / "Resources" / "Legal" / "third-party" / "native" / formula
    copied: list[str] = []
    accepted = {"copying", "copyright", "license", "license.txt", "notice"}
    for source in sorted(keg_root.iterdir()):
        if source.name.lower() not in accepted or not source.is_file():
            continue
        destination = legal_root / source.name
        _copy_distinct_file(source, destination)
        copied.append(source.name)
    if not copied:
        raise ValueError(f"native provider has no redistributable license: {formula}")
    return copied


def _homebrew_provider(path: Path) -> tuple[str, str, Path, Path]:
    cellar = Path("/opt/homebrew/Cellar")
    relative = _relative_to(path, cellar)
    if relative is None or len(relative.parts) < 3:
        raise ValueError(f"unsupported native dependency provider: {path}")
    formula, version = relative.parts[:2]
    keg_root = cellar / formula / version
    return formula, version, keg_root, Path(*relative.parts[2:])


def _materialize_absolute_dependency(
    *,
    dependency: str,
    inputs: RuntimeBuildInputs,
    payload: Path,
    providers: dict[str, dict[str, object]],
    materialized_sources: dict[Path, tuple[Path, str]],
) -> Path:
    source = Path(dependency).resolve(strict=True)
    python_source = inputs.python_prefix.resolve(strict=True)
    postgres_source = inputs.postgresql_prefix.resolve(strict=True)
    pgvector_source = inputs.pgvector_prefix.resolve(strict=True)
    python_relative = _relative_to(source, python_source)
    if python_relative is not None:
        return payload / "Contents" / "Resources" / "runtime" / "python" / python_relative
    postgres_relative = _relative_to(source, postgres_source)
    if postgres_relative is not None:
        return payload / "Contents" / "Resources" / "runtime" / "postgresql" / postgres_relative
    pgvector_relative = _relative_to(source, pgvector_source)
    if pgvector_relative == Path("lib/postgresql@17/vector.dylib"):
        return (
            payload
            / "Contents"
            / "Resources"
            / "runtime"
            / "postgresql"
            / "lib"
            / "postgresql"
            / "vector.dylib"
        )
    formula, version, keg_root, provider_relative = _homebrew_provider(source)
    destination = (
        payload
        / "Contents"
        / "Resources"
        / "runtime"
        / "native"
        / formula
        / version
        / provider_relative
    )
    source_sha256 = hashlib.sha256(source.read_bytes()).hexdigest()
    previous_source = materialized_sources.get(destination)
    if previous_source is not None:
        if previous_source[1] != source_sha256:
            raise ValueError("native dependency destination collision")
    else:
        _copy_distinct_file(source, destination)
        materialized_sources[destination] = (source, source_sha256)
    key = f"{formula}/{version}"
    if key not in providers:
        receipt = keg_root / "INSTALL_RECEIPT.json"
        if not receipt.is_file():
            raise ValueError(f"native provider receipt is missing: {formula}")
        providers[key] = {
            "formula": formula,
            "licenses": _copy_native_provider_legal(
                keg_root=keg_root,
                formula=formula,
                payload=payload,
            ),
            "receipt_sha256": hashlib.sha256(receipt.read_bytes()).hexdigest(),
            "version": version,
            "files": [],
        }
    files = providers[key]["files"]
    if not isinstance(files, list):
        raise AssertionError("native provider file inventory is invalid")
    relative_text = provider_relative.as_posix()
    if relative_text not in files:
        files.append(relative_text)
        files.sort()
    return destination


def _loader_reference(*, loader: Path, dependency: Path) -> str:
    relative = os.path.relpath(dependency, loader.parent)
    if relative == ".":
        raise ValueError("Mach-O image cannot load itself")
    return f"@loader_path/{Path(relative).as_posix()}"


def _source_token_dependency(
    *,
    name: str,
    source_image: Path,
    rpaths: tuple[str, ...],
) -> Path:
    if name.startswith("@loader_path/"):
        return (source_image.parent / name.removeprefix("@loader_path/")).resolve(strict=True)
    if name.startswith("@rpath/"):
        suffix = name.removeprefix("@rpath/")
        for rpath in rpaths:
            if rpath.startswith("@loader_path"):
                prefix = rpath.removeprefix("@loader_path").lstrip("/")
                candidate = source_image.parent / prefix / suffix
            elif rpath.startswith("/"):
                candidate = Path(rpath) / suffix
            else:
                continue
            if candidate.exists():
                return candidate.resolve(strict=True)
        raise ValueError(f"provider has unresolved @rpath dependency: {name}")
    raise ValueError(f"unsupported unresolved provider dependency: {name}")


def _adhoc_sign_macho(image: Path) -> None:
    result = subprocess.run(
        [
            "/usr/bin/codesign",
            "--force",
            "--sign",
            "-",
            "--timestamp=none",
            str(image),
        ],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise ValueError(f"ad hoc signing failed for {image.name}")


def relocate_runtime_dependencies(
    *,
    inputs: RuntimeBuildInputs,
    payload: Path,
) -> dict[str, object]:
    """Materialize and rewrite all non-system absolute dependencies in the payload."""
    providers: dict[str, dict[str, object]] = {}
    materialized_sources: dict[Path, tuple[Path, str]] = {}
    changes = 0
    signed_images: set[Path] = set()
    while True:
        copied_or_changed = False
        images = [candidate for candidate in sorted(payload.rglob("*")) if is_macho(candidate)]
        for image in images:
            commands = read_macho_commands(image)
            arguments: list[str] = ["/usr/bin/install_name_tool"]
            image_changes = 0
            if commands.identifier is not None and commands.identifier.startswith("/"):
                arguments.extend(["-id", f"@rpath/{image.name}"])
                image_changes += 1
            for rpath in commands.rpaths:
                if rpath.startswith("/"):
                    arguments.extend(["-delete_rpath", rpath])
                    image_changes += 1
            for load in commands.loads:
                if load.name.startswith(("/System/Library/", "/usr/lib/")):
                    continue
                if load.name.startswith("/"):
                    source_dependency = load.name
                else:
                    try:
                        resolve_load_path(
                            load.name,
                            loader=image,
                            executable=image,
                            rpaths=commands.rpaths,
                            bundle_root=payload,
                        )
                        continue
                    except ValueError:
                        source_record = materialized_sources.get(image)
                        if source_record is None:
                            raise
                        source_dependency = str(
                            _source_token_dependency(
                                name=load.name,
                                source_image=source_record[0],
                                rpaths=commands.rpaths,
                            )
                        )
                target = _materialize_absolute_dependency(
                    dependency=source_dependency,
                    inputs=inputs,
                    payload=payload,
                    providers=providers,
                    materialized_sources=materialized_sources,
                )
                if not target.is_file():
                    raise ValueError(f"mapped native dependency is missing: {load.name}")
                replacement = _loader_reference(loader=image, dependency=target)
                arguments.extend(["-change", load.name, replacement])
                image_changes += 1
            if len(arguments) == 1:
                continue
            result = subprocess.run([*arguments, str(image)], capture_output=True, text=True)
            if result.returncode != 0:
                raise ValueError(f"install_name_tool failed for {image.name}")
            _adhoc_sign_macho(image)
            signed_images.add(image)
            changes += image_changes
            copied_or_changed = True
        if not copied_or_changed:
            break
    closure = verify_macho_closure(payload)
    return {
        "bundled_loads": closure.bundled_loads,
        "changes": changes,
        "staging_adhoc_signed_images": len(signed_images),
        "images": closure.images,
        "loads": closure.loads,
        "providers": [providers[key] for key in sorted(providers)],
        "system_loads": closure.system_loads,
    }


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
        macho_closure = relocate_runtime_dependencies(inputs=inputs, payload=payload)
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
            "macho_closure": macho_closure,
            "runtime_tree_sha256": _tree_sha256(payload / "Contents" / "Resources" / "runtime"),
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
