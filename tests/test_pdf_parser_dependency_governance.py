from __future__ import annotations

import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).parents[1]
MANIFEST = ROOT / "docs/dependency-governance/pdf-parser-candidates.json"
APPROVAL = ROOT / "docs/dependency-governance/pdf-parser-approval.md"
AUDITOR = ROOT / "script/audit_pdf_parser_dependencies.py"
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


def _load_manifest() -> dict[str, Any]:
    return json.loads(MANIFEST.read_text())


def _load_approval() -> dict[str, Any]:
    text = APPROVAL.read_text()
    payload = text.split("<!-- RSI_ATLAS_PDF_PARSER_APPROVAL_BEGIN -->", 1)[1]
    payload = payload.split("<!-- RSI_ATLAS_PDF_PARSER_APPROVAL_END -->", 1)[0].strip()
    return json.loads(payload.removeprefix("```json\n").removesuffix("\n```"))


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _candidate(manifest: dict[str, Any], candidate_id: str) -> dict[str, Any]:
    return next(item for item in manifest["candidates"] if item["id"] == candidate_id)


def test_pdf_parser_governance_artifacts_exist_before_dependency_installation() -> None:
    assert MANIFEST.is_file()
    assert APPROVAL.is_file()
    assert AUDITOR.is_file()


def test_manifest_is_bound_to_the_unchanged_accepted_workspace() -> None:
    manifest = _load_manifest()

    assert manifest["schema_version"] == "rsi-atlas.pdf-parser-governance.v1"
    assert SHA256_RE.fullmatch(manifest["manifest_sha256"])
    assert manifest["baseline"] == {
        "package_count": 52,
        "pyproject_sha256": _sha256(ROOT / "pyproject.toml"),
        "uv_lock_sha256": _sha256(ROOT / "uv.lock"),
        "uv_lock_version": 1,
        "uv_version": "0.5.23",
    }
    assert manifest["target_environment"] == {
        "implementation": "CPython",
        "machine": "arm64",
        "platform": "macOS",
        "python_version": "3.12.13",
        "service_scope": "document-worker-only",
    }
    assert manifest["policy"]["requires_explicit_approval"] is True
    assert manifest["policy"]["wheel_only"] is True


def test_tier_zero_candidates_have_exact_reviewed_target_wheels() -> None:
    manifest = _load_manifest()
    pypdf = _candidate(manifest, "pypdf-base")
    pdfminer = _candidate(manifest, "pdfminer-six-base")

    assert (pypdf["version"], pypdf["extras"], len(pypdf["components"])) == (
        "6.14.2",
        [],
        1,
    )
    assert (pdfminer["version"], pdfminer["extras"], len(pdfminer["components"])) == (
        "20260107",
        [],
        5,
    )
    assert pypdf["scratch_lock"]["sha256"] == (
        "a8895666baea08af2eea1ea5cd77d681c902a5db8f6ba289f0dda535733a29a0"
    )
    assert pdfminer["scratch_lock"]["sha256"] == (
        "a03ca8b7b57f8bd57201a0fae4722296d852fe1e997595313bd1e5d5db6381d7"
    )

    for candidate in (pypdf, pdfminer):
        assert candidate["status"] == "awaiting_explicit_approval"
        assert candidate["installation_eligible"] is False
        assert candidate["blockers"] == ["explicit_dependency_approval_required"]
        for component in candidate["components"]:
            assert component["license_expression"]
            assert component["license_evidence_status"] == "reviewed_wheel_metadata"
            assert component["behavior_review"]["review_status"] == "reviewed"
            assert component["selected_target_artifact"] is not None
            assert component["known_advisory_ids"] == []


def test_docling_remains_blocked_with_source_and_runtime_risks_recorded() -> None:
    candidate = _candidate(_load_manifest(), "docling-standard-benchmark")

    assert candidate["version"] == "2.113.0"
    assert candidate["extras"] == ["standard"]
    assert candidate["tier"] == "tier-1-benchmark-only"
    assert candidate["status"] == "blocked_dependency_governance"
    assert candidate["installation_eligible"] is False
    assert len(candidate["components"]) == 123
    assert candidate["scratch_lock"]["sha256"] == (
        "6631ce0a00322e28d0d82179eaa0411c0adf67a2aa622ae908c45465a78e7089"
    )
    assert candidate["blockers"] == [
        "license_evidence_incomplete",
        "model_artifacts_unreviewed",
        "native_dynamic_load_surface",
        "remote_code_supported",
        "runtime_model_download",
        "source_distribution_requires_build",
        "unsafe_deserialization_surface",
    ]

    antlr = next(
        component
        for component in candidate["components"]
        if component["purl"] == "pkg:pypi/antlr4-python3-runtime@4.9.3"
    )
    assert [artifact["kind"] for artifact in antlr["artifacts"]] == ["sdist"]
    assert antlr["artifacts"][0]["sha256"] == (
        "f224469b4168294902bb1efa80a8bf7855f24c99aef99cbefc1bcd3cce77881b"
    )
    docling = next(component for component in candidate["components"] if component["direct"])
    assert docling["behavior_review"] == {
        "dynamically_loads_native_code": False,
        "fetches_urls_at_runtime": True,
        "imports_remote_code": True,
        "review_status": "candidate_blocked_unreviewed",
        "unsafe_deserialization_surface": True,
    }


def test_every_component_and_artifact_has_content_addressed_evidence() -> None:
    manifest = _load_manifest()
    unique_purls: set[str] = set()

    for candidate in manifest["candidates"]:
        assert candidate["components"] == sorted(
            candidate["components"], key=lambda item: (item["name"], item["version"])
        )
        for component in candidate["components"]:
            assert component["purl"] not in unique_purls or candidate["id"].startswith("docling")
            unique_purls.add(component["purl"])
            assert component["purl"] == (f"pkg:pypi/{component['name']}@{component['version']}")
            assert component["source_registry"] == "https://pypi.org/simple"
            assert isinstance(component["known_advisory_ids"], list)
            assert isinstance(component["selected_wheel_license_files"], list)
            if component["license_evidence_status"] == "reviewed_wheel_metadata":
                assert component["selected_wheel_license_files"]
            for license_file in component["selected_wheel_license_files"]:
                assert set(license_file) == {"path", "sha256"}
                assert SHA256_RE.fullmatch(license_file["sha256"])
            assert set(component["behavior_review"]) == {
                "dynamically_loads_native_code",
                "fetches_urls_at_runtime",
                "imports_remote_code",
                "review_status",
                "unsafe_deserialization_surface",
            }
            for artifact in component["artifacts"]:
                assert artifact["source_url"].startswith("https://files.pythonhosted.org/")
                assert SHA256_RE.fullmatch(artifact["sha256"])
                assert artifact["size_bytes"] > 0
                assert set(artifact) == {
                    "filename",
                    "kind",
                    "platform_python_tags",
                    "publisher_attestation",
                    "sha256",
                    "size_bytes",
                    "source_url",
                }

    assert manifest["advisory_snapshot"]["provider"] == "OSV"
    assert manifest["advisory_snapshot"]["query_count"] == len(unique_purls)
    assert SHA256_RE.fullmatch(manifest["advisory_snapshot"]["request_sha256"])
    assert SHA256_RE.fullmatch(manifest["advisory_snapshot"]["response_sha256"])


def test_approved_tier0_is_narrow_and_keeps_manifest_non_installable() -> None:
    approval = _load_approval()
    manifest = _load_manifest()

    assert approval["schema_version"] == "rsi-atlas.pdf-parser-approval.v1"
    assert approval["decision"] == "approved"
    assert approval["actor_id"] == "andrzej:continue-development-instruction"
    assert approval["decided_at"] == "2026-07-19T08:18:00Z"
    assert approval["manifest_sha256"] == manifest["manifest_sha256"]
    assert approval["accepted_exceptions"] == []
    assert approval["model_artifacts"] == []
    assert [item["id"] for item in approval["proposed_candidates"]] == [
        "pypdf-base",
        "pdfminer-six-base",
    ]
    assert approval["blocked_candidates"] == [
        {
            "id": "docling-standard-benchmark",
            "reason": "blocked_dependency_governance",
            "requirement": "docling==2.113.0",
        }
    ]
    assert approval["authority"] == {
        "allows_commit_or_push": False,
        "allows_dependency_lock_change": True,
        "allows_model_artifacts": False,
        "allows_production_promotion": False,
        "allows_runtime_network": False,
        "package_scope": "document-worker-only",
    }
    # Governance manifest remains fail-closed; approval authorizes a later document-worker lock
    # change without flipping installation_eligible on the review record itself.
    assert all(candidate["installation_eligible"] is False for candidate in manifest["candidates"])


def test_offline_auditor_reproduces_a_cyclonedx_sbom(tmp_path: Path) -> None:
    sbom_path = tmp_path / "phase-2b-sbom.json"

    result = subprocess.run(
        [
            sys.executable,
            str(AUDITOR),
            "verify",
            "--manifest",
            str(MANIFEST),
            "--approval",
            str(APPROVAL),
            "--sbom-out",
            str(sbom_path),
        ],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    sbom = json.loads(sbom_path.read_text())
    assert sbom["bomFormat"] == "CycloneDX"
    assert sbom["specVersion"] == "1.6"
    assert len(sbom["components"]) == 128
    assert len({component["bom-ref"] for component in sbom["components"]}) == 128
    assert sbom["metadata"]["properties"] == [
        {
            "name": "rsi-atlas:manifest-sha256",
            "value": _load_manifest()["manifest_sha256"],
        }
    ]
