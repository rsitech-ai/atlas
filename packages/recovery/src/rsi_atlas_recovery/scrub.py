"""Integrity scrub against a backup or artifact manifest."""

from __future__ import annotations

from datetime import datetime
from hashlib import sha256
from pathlib import Path

from rsi_atlas_contracts import (
    BackupManifest,
    IntegrityFindingKind,
    IntegrityScrubFinding,
    IntegrityScrubReport,
    scrub_id,
)


def scrub_against_manifest(
    root: Path,
    manifest: BackupManifest,
    *,
    created_at: datetime,
) -> IntegrityScrubReport:
    findings: list[IntegrityScrubFinding] = []
    for entry in manifest.entries:
        path = root / entry.path
        if not path.is_file():
            findings.append(
                IntegrityScrubFinding(
                    path=entry.path,
                    kind=IntegrityFindingKind.MISSING,
                    expected_sha256=entry.sha256,
                )
            )
            continue
        actual = sha256(path.read_bytes()).hexdigest()
        if actual != entry.sha256:
            findings.append(
                IntegrityScrubFinding(
                    path=entry.path,
                    kind=IntegrityFindingKind.MODIFIED,
                    expected_sha256=entry.sha256,
                    actual_sha256=actual,
                )
            )
        else:
            findings.append(
                IntegrityScrubFinding(
                    path=entry.path,
                    kind=IntegrityFindingKind.OK,
                    expected_sha256=entry.sha256,
                    actual_sha256=actual,
                )
            )
    bad = [f for f in findings if f.kind is not IntegrityFindingKind.OK]
    return IntegrityScrubReport(
        scrub_id=scrub_id(root_hash=manifest.root_hash, created_at=created_at),
        findings=tuple(findings),
        healthy=not bad,
        created_at=created_at,
    )
