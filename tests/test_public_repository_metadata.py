from __future__ import annotations

import re
import subprocess
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EXTERNAL_REVISION_IDS = {
    # Pinned upstream Hugging Face model revision.
    "1110a243fdf4706b3f48f1d95db1a4f5529b4d41",
    # Historical local review-agent identifier, not a repository commit.
    "3b72a54e",
}


def _project_metadata(path: Path) -> dict[str, object]:
    return tomllib.loads(path.read_text(encoding="utf-8"))["project"]


def test_public_owner_maintainer_and_repository_metadata_are_canonical() -> None:
    project = _project_metadata(ROOT / "pyproject.toml")

    assert project["license"] == "Apache-2.0"
    assert project["authors"] == [{"name": "Rafal Sikora"}]
    assert project["maintainers"] == [{"name": "RSI Tech", "email": "info@rsitech.ai"}]
    assert project["urls"] == {
        "Homepage": "https://rsitech.ai",
        "Repository": "https://github.com/rsitech-ai/atlas",
        "Issues": "https://github.com/rsitech-ai/atlas/issues",
        "Documentation": "https://github.com/rsitech-ai/atlas#readme",
    }


def test_public_copy_uses_the_canonical_owner_brand_and_contact() -> None:
    notice = (ROOT / "NOTICE").read_text(encoding="utf-8")
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    security = (ROOT / "SECURITY.md").read_text(encoding="utf-8")

    assert "Copyright 2026 Rafal Sikora" in notice
    assert "Publicly maintained by RSI Tech (https://rsitech.ai)." in notice
    assert "[RSI Tech](https://rsitech.ai)" in readme
    assert "info@rsitech.ai" in notice
    assert "info@rsitech.ai" in readme
    assert "info@rsitech.ai" in security
    assert "github.com/s1korrrr/atlas" not in notice + readme


def test_every_workspace_package_keeps_apache_2_license() -> None:
    root_document = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    members = root_document["tool"]["uv"]["workspace"]["members"]
    assert len(members) == 16
    assert all(
        _project_metadata(ROOT / member / "pyproject.toml")["license"] == "Apache-2.0"
        for member in members
    )


def test_internal_agent_reports_are_not_part_of_the_public_tree() -> None:
    assert not (ROOT / ".superpowers" / "sdd" / "task-1-report.md").exists()
    assert not (ROOT / ".superpowers" / "sdd" / "task-4-report.md").exists()


def test_repository_commit_evidence_is_reachable_from_published_head() -> None:
    failures: list[str] = []
    reachable_commits = subprocess.run(
        ["git", "rev-list", "HEAD"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.splitlines()
    for directory in (ROOT / "docs", ROOT / "plans"):
        for path in directory.rglob("*.md"):
            text = path.read_text(encoding="utf-8")
            for match in re.finditer(r"`([0-9a-f]{7,40})`", text):
                revision = match.group(1)
                if revision in EXTERNAL_REVISION_IDS:
                    continue
                location = f"{path.relative_to(ROOT)}:{text.count(chr(10), 0, match.start()) + 1}"
                matches = [commit for commit in reachable_commits if commit.startswith(revision)]
                if len(matches) != 1:
                    failures.append(
                        f"{location}: {revision} matches {len(matches)} commits reachable from HEAD"
                    )

    assert not failures, "\n".join(failures)
