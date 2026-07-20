"""Fail-closed shell release workflow contracts."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]


def test_package_release_assembles_before_release_gate() -> None:
    script = (ROOT / "script" / "package_release.sh").read_text(encoding="utf-8")

    assembly = script.index("assemble_release_app.py")
    release_gate = script.index("release_check.py --require-release")
    assert assembly < release_gate
    assert "git rev-list --count HEAD" in script
