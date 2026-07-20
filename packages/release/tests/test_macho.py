from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
from rsi_atlas_release.macho import (
    MachOLoad,
    MachOParseError,
    parse_otool_load_commands,
    resolve_load_path,
    verify_macho_closure,
)


def test_parser_ignores_fat_architecture_headers_and_preserves_load_kinds() -> None:
    output = """
/tmp/libsample.dylib (architecture x86_64):
Load command 0
          cmd LC_ID_DYLIB
      cmdsize 56
         name @rpath/libsample.dylib (offset 24)
/tmp/libsample.dylib (architecture arm64):
Load command 0
          cmd LC_ID_DYLIB
      cmdsize 56
         name @rpath/libsample.dylib (offset 24)
Load command 1
          cmd LC_LOAD_WEAK_DYLIB
      cmdsize 64
         name /usr/lib/libSystem.B.dylib (offset 24)
Load command 2
          cmd LC_REEXPORT_DYLIB
      cmdsize 64
         name @loader_path/libchild.dylib (offset 24)
Load command 3
          cmd LC_RPATH
      cmdsize 48
         path @loader_path/.dylibs (offset 12)
"""

    parsed = parse_otool_load_commands(output, architecture="arm64")

    assert parsed.identifier == "@rpath/libsample.dylib"
    assert parsed.loads == (
        MachOLoad("LC_LOAD_WEAK_DYLIB", "/usr/lib/libSystem.B.dylib"),
        MachOLoad("LC_REEXPORT_DYLIB", "@loader_path/libchild.dylib"),
    )
    assert parsed.rpaths == ("@loader_path/.dylibs",)


@pytest.mark.parametrize(
    ("load_name", "expected"),
    [
        ("@loader_path/../Frameworks/libA.dylib", "Contents/Frameworks/libA.dylib"),
        ("@executable_path/../Frameworks/libA.dylib", "Contents/Frameworks/libA.dylib"),
        ("@rpath/libA.dylib", "Contents/Frameworks/libA.dylib"),
    ],
)
def test_resolver_handles_dyld_tokens_inside_bundle(
    tmp_path: Path,
    load_name: str,
    expected: str,
) -> None:
    bundle = tmp_path / "RSIAtlas.app"
    loader = bundle / "Contents" / "MacOS" / "helper"
    executable = bundle / "Contents" / "MacOS" / "RSIAtlas"
    framework = bundle / "Contents" / "Frameworks" / "libA.dylib"
    loader.parent.mkdir(parents=True)
    framework.parent.mkdir(parents=True)
    loader.touch()
    executable.touch()
    framework.touch()

    resolved = resolve_load_path(
        load_name,
        loader=loader,
        executable=executable,
        rpaths=("@executable_path/../Frameworks",),
        bundle_root=bundle,
    )

    assert resolved == bundle / expected


def test_resolver_allows_only_exact_apple_system_roots(tmp_path: Path) -> None:
    bundle = tmp_path / "RSIAtlas.app"
    loader = bundle / "Contents" / "MacOS" / "helper"

    assert (
        resolve_load_path(
            "/System/Library/Frameworks/AppKit.framework/AppKit",
            loader=loader,
            executable=loader,
            rpaths=(),
            bundle_root=bundle,
        )
        is None
    )
    assert (
        resolve_load_path(
            "/usr/lib/libSystem.B.dylib",
            loader=loader,
            executable=loader,
            rpaths=(),
            bundle_root=bundle,
        )
        is None
    )
    with pytest.raises(ValueError, match="non-system absolute dependency"):
        resolve_load_path(
            "/usr/local/lib/libInjected.dylib",
            loader=loader,
            executable=loader,
            rpaths=(),
            bundle_root=bundle,
        )


def test_resolver_rejects_token_escape_and_unresolved_rpath(tmp_path: Path) -> None:
    bundle = tmp_path / "RSIAtlas.app"
    loader = bundle / "Contents" / "MacOS" / "helper"
    loader.parent.mkdir(parents=True)
    loader.touch()

    with pytest.raises(ValueError, match="escapes the application bundle"):
        resolve_load_path(
            "@loader_path/../../../../outside.dylib",
            loader=loader,
            executable=loader,
            rpaths=(),
            bundle_root=bundle,
        )
    with pytest.raises(ValueError, match="unresolved @rpath dependency"):
        resolve_load_path(
            "@rpath/missing.dylib",
            loader=loader,
            executable=loader,
            rpaths=("@loader_path/.dylibs",),
            bundle_root=bundle,
        )


def test_parser_rejects_incomplete_load_command() -> None:
    with pytest.raises(MachOParseError, match="missing name"):
        parse_otool_load_commands(
            "Load command 0\n          cmd LC_LOAD_DYLIB\n      cmdsize 56\n",
            architecture="arm64",
        )


def test_live_closure_rejects_absolute_identifier(tmp_path: Path) -> None:
    library = tmp_path / "RSIAtlas.app" / "Contents" / "Frameworks" / "libsample.dylib"
    library.parent.mkdir(parents=True)
    source = tmp_path / "sample.c"
    source.write_text("int sample(void) { return 1; }\n", encoding="utf-8")
    subprocess.run(
        [
            "/usr/bin/clang",
            "-arch",
            "arm64",
            "-dynamiclib",
            "-install_name",
            "/tmp/libsample.dylib",
            str(source),
            "-o",
            str(library),
        ],
        check=True,
        capture_output=True,
        text=True,
    )

    with pytest.raises(ValueError, match="absolute Mach-O identifier"):
        verify_macho_closure(tmp_path / "RSIAtlas.app")

    subprocess.run(
        ["/usr/bin/install_name_tool", "-id", "@rpath/libsample.dylib", str(library)],
        check=True,
        capture_output=True,
        text=True,
    )
    closure = verify_macho_closure(tmp_path / "RSIAtlas.app")
    assert closure.images == 1
    assert closure.loads >= 1

    subprocess.run(
        ["/usr/bin/install_name_tool", "-add_rpath", "/tmp/injected", str(library)],
        check=True,
        capture_output=True,
        text=True,
    )
    with pytest.raises(ValueError, match="absolute Mach-O rpath"):
        verify_macho_closure(tmp_path / "RSIAtlas.app")

    subprocess.run(
        ["/usr/bin/install_name_tool", "-delete_rpath", "/tmp/injected", str(library)],
        check=True,
        capture_output=True,
        text=True,
    )
    subprocess.run(
        ["/usr/bin/install_name_tool", "-add_rpath", "/usr/lib/swift", str(library)],
        check=True,
        capture_output=True,
        text=True,
    )
    verify_macho_closure(tmp_path / "RSIAtlas.app")
