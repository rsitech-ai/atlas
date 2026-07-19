#!/usr/bin/env python3
"""Capture and verify the Phase 2B PDF parser dependency-governance record.

Capture is an explicit, networked review operation against scratch uv locks. Verification is
offline and fail-closed: it validates the committed manifest, accepted workspace baseline, and
machine-readable approval record without importing or installing any parser candidate.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import tomllib
import urllib.request
import zipfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

ROOT = Path(__file__).parents[1]
DEFAULT_MANIFEST = ROOT / "docs/dependency-governance/pdf-parser-candidates.json"
DEFAULT_APPROVAL = ROOT / "docs/dependency-governance/pdf-parser-approval.md"
DEFAULT_SBOM = ROOT / ".superpowers/sdd/phase-2b-sbom.json"
SCHEMA_VERSION = "rsi-atlas.pdf-parser-governance.v1"
APPROVAL_SCHEMA = "rsi-atlas.pdf-parser-approval.v1"
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
UTC_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
VIRTUAL_ROOT_PREFIX = "rsi-atlas-"

CANDIDATES = (
    {
        "id": "pypdf-base",
        "distribution": "pypdf",
        "import_name": "pypdf",
        "version": "6.14.2",
        "tier": "tier-0-preflight",
        "extras": [],
        "lock_dir": "pypdf",
        "lock_sha256": "a8895666baea08af2eea1ea5cd77d681c902a5db8f6ba289f0dda535733a29a0",
        "component_count": 1,
        "status": "awaiting_explicit_approval",
        "blockers": ["explicit_dependency_approval_required"],
    },
    {
        "id": "pdfminer-six-base",
        "distribution": "pdfminer-six",
        "import_name": "pdfminer",
        "version": "20260107",
        "tier": "tier-0-layout",
        "extras": [],
        "lock_dir": "pdfminer",
        "lock_sha256": "a03ca8b7b57f8bd57201a0fae4722296d852fe1e997595313bd1e5d5db6381d7",
        "component_count": 5,
        "status": "awaiting_explicit_approval",
        "blockers": ["explicit_dependency_approval_required"],
    },
    {
        "id": "docling-standard-benchmark",
        "distribution": "docling",
        "import_name": "docling",
        "version": "2.113.0",
        "tier": "tier-1-benchmark-only",
        "extras": ["standard"],
        "lock_dir": "docling",
        "lock_sha256": "6631ce0a00322e28d0d82179eaa0411c0adf67a2aa622ae908c45465a78e7089",
        "component_count": 123,
        "status": "blocked_dependency_governance",
        "blockers": [
            "license_evidence_incomplete",
            "model_artifacts_unreviewed",
            "native_dynamic_load_surface",
            "remote_code_supported",
            "runtime_model_download",
            "source_distribution_requires_build",
            "unsafe_deserialization_surface",
        ],
    },
)

TIER0_LICENSES = {
    ("cffi", "2.1.0"): "MIT-0",
    ("charset-normalizer", "3.4.9"): "MIT",
    ("cryptography", "49.0.0"): "Apache-2.0 OR BSD-3-Clause",
    ("pdfminer-six", "20260107"): "MIT",
    ("pycparser", "3.0"): "BSD-3-Clause",
    ("pypdf", "6.14.2"): "BSD-3-Clause",
}


class GovernanceError(ValueError):
    """Raised when governance evidence is incomplete or internally inconsistent."""


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _sha256_file(path: Path) -> str:
    return _sha256_bytes(path.read_bytes())


def _canonical_bytes(value: Any) -> bytes:
    return (
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True) + "\n"
    ).encode()


def _manifest_digest(manifest: dict[str, Any]) -> str:
    subject = dict(manifest)
    subject.pop("manifest_sha256", None)
    return _sha256_bytes(_canonical_bytes(subject))


def _approval_digest(approval: dict[str, Any]) -> str:
    subject = dict(approval)
    subject.pop("approval_sha256", None)
    return _sha256_bytes(_canonical_bytes(subject))


def _normalize_name(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise GovernanceError(message)


def _load_lock(path: Path) -> dict[str, Any]:
    _require(path.is_file(), f"scratch lock is missing: {path}")
    with path.open("rb") as handle:
        return tomllib.load(handle)


def _artifact(raw: dict[str, Any], kind: str) -> dict[str, Any]:
    url = raw["url"]
    filename = unquote(Path(urlparse(url).path).name)
    digest = raw["hash"].removeprefix("sha256:")
    return {
        "filename": filename,
        "kind": kind,
        "platform_python_tags": filename.rsplit(".", 1)[0].split("-")[-3:]
        if kind == "wheel"
        else [],
        "publisher_attestation": None,
        "sha256": digest,
        "size_bytes": raw["size"],
        "source_url": url,
    }


def _fetch_json(url: str, *, payload: bytes | None = None) -> tuple[dict[str, Any], bytes]:
    headers = {"Accept": "application/json", "User-Agent": "rsi-atlas-governance/1"}
    if payload is not None:
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(
        url, data=payload, headers=headers, method="POST" if payload else "GET"
    )
    with urllib.request.urlopen(request, timeout=60) as response:
        body = response.read()
    return json.loads(body), body


def _pypi_metadata(name: str, version: str) -> dict[str, Any]:
    data, _ = _fetch_json(f"https://pypi.org/pypi/{name}/{version}/json")
    info = data["info"]
    return {
        "license_expression": info.get("license_expression") or None,
        "license_legacy": info.get("license") or None,
        "project_url": info.get("project_url") or info.get("package_url"),
        "requires_python": info.get("requires_python"),
    }


def _selected_artifact(component: dict[str, Any], cache: Path) -> dict[str, Any] | None:
    name = _normalize_name(component["name"])
    version = component["version"]
    for path in sorted(cache.rglob("*")):
        if not path.is_file():
            continue
        filename = path.name.lower().replace("_", "-")
        if filename.startswith(f"{name}-{version}".lower()):
            digest = _sha256_file(path)
            candidates = [*component["artifacts"]]
            for artifact in candidates:
                if artifact["sha256"] == digest and artifact["size_bytes"] == path.stat().st_size:
                    return {
                        "filename": artifact["filename"],
                        "sha256": digest,
                        "size_bytes": path.stat().st_size,
                    }
            raise GovernanceError(f"review-cache artifact is absent from lock: {path}")
    return None


def _selected_license_files(
    selected_artifact: dict[str, Any] | None, cache: Path
) -> list[dict[str, str]]:
    if selected_artifact is None or not selected_artifact["filename"].endswith(".whl"):
        return []
    matching_paths = sorted(cache.rglob(selected_artifact["filename"]))
    _require(
        len(matching_paths) == 1,
        f"selected wheel is missing or duplicated in review cache: {selected_artifact['filename']}",
    )
    wheel_path = matching_paths[0]
    evidence = []
    with zipfile.ZipFile(wheel_path) as archive:
        for name in sorted(archive.namelist()):
            if name.endswith("/"):
                continue
            basename = Path(name).name.lower()
            if not basename or not basename.startswith(("license", "copying", "notice")):
                continue
            content = archive.read(name)
            evidence.append({"path": name, "sha256": _sha256_bytes(content)})
    return evidence


def _component(
    raw: dict[str, Any],
    *,
    direct_name: str,
    cache: Path,
    pypi: dict[tuple[str, str], dict[str, Any]],
) -> dict[str, Any]:
    name = _normalize_name(raw["name"])
    version = raw["version"]
    artifacts: list[dict[str, Any]] = []
    if "sdist" in raw:
        artifacts.append(_artifact(raw["sdist"], "sdist"))
    artifacts.extend(_artifact(item, "wheel") for item in raw.get("wheels", []))
    artifacts.sort(key=lambda item: (item["kind"], item["filename"], item["sha256"]))
    license_expression = (
        TIER0_LICENSES.get((name, version)) or pypi[(name, version)]["license_expression"]
    )
    license_status = (
        "reviewed_wheel_metadata" if (name, version) in TIER0_LICENSES else "metadata_only"
    )
    dependencies = sorted({_normalize_name(item["name"]) for item in raw.get("dependencies", [])})
    component = {
        "artifacts": artifacts,
        "behavior_review": {
            "dynamically_loads_native_code": name
            in {"cffi", "cryptography", "docling-parse", "torch"},
            "fetches_urls_at_runtime": name
            in {"docling", "docling-slim", "huggingface-hub", "requests"},
            "imports_remote_code": name in {"docling", "transformers"},
            "review_status": "reviewed"
            if (name, version) in TIER0_LICENSES
            else "candidate_blocked_unreviewed",
            "unsafe_deserialization_surface": name
            in {"docling", "docling-ibm-models", "torch", "transformers"},
        },
        "dependencies": dependencies,
        "direct": name == _normalize_name(direct_name),
        "license_evidence_status": license_status,
        "license_expression": license_expression,
        "name": name,
        "project_url": pypi[(name, version)]["project_url"],
        "purl": f"pkg:pypi/{name}@{version}",
        "requires_python": pypi[(name, version)]["requires_python"],
        "selected_target_artifact": None,
        "source_registry": raw.get("source", {}).get("registry"),
        "version": version,
    }
    component["selected_target_artifact"] = _selected_artifact(component, cache)
    component["selected_wheel_license_files"] = _selected_license_files(
        component["selected_target_artifact"], cache
    )
    return component


def capture(scratch_root: Path, output: Path) -> None:
    generated_at = datetime.now(UTC).replace(microsecond=0).strftime("%Y-%m-%dT%H:%M:%SZ")
    locks: dict[str, tuple[Path, dict[str, Any], list[dict[str, Any]]]] = {}
    identities: set[tuple[str, str]] = set()
    for candidate in CANDIDATES:
        lock_path = scratch_root / "candidates" / candidate["lock_dir"] / "uv.lock"
        _require(
            _sha256_file(lock_path) == candidate["lock_sha256"],
            f"scratch lock hash changed: {lock_path}",
        )
        lock = _load_lock(lock_path)
        packages = [
            item
            for item in lock["package"]
            if not (
                item.get("source", {}).get("virtual")
                and item["name"].startswith(VIRTUAL_ROOT_PREFIX)
            )
        ]
        _require(
            len(packages) == candidate["component_count"],
            f"component count changed: {candidate['id']}",
        )
        locks[candidate["id"]] = (lock_path, lock, packages)
        identities.update((_normalize_name(item["name"]), item["version"]) for item in packages)

    pypi = {identity: _pypi_metadata(*identity) for identity in sorted(identities)}
    osv_query = {
        "queries": [
            {"package": {"ecosystem": "PyPI", "name": name}, "version": version}
            for name, version in sorted(identities)
        ]
    }
    osv_payload = _canonical_bytes(osv_query)
    osv_data, osv_body = _fetch_json("https://api.osv.dev/v1/querybatch", payload=osv_payload)
    _require(
        len(osv_data.get("results", [])) == len(identities), "OSV returned an incomplete batch"
    )
    advisories = {
        identity: sorted({vulnerability["id"] for vulnerability in result.get("vulns", [])})
        for identity, result in zip(sorted(identities), osv_data["results"], strict=True)
    }

    candidates = []
    for definition in CANDIDATES:
        lock_path, lock, packages = locks[definition["id"]]
        cache = scratch_root / "review-cache"
        components = [
            _component(item, direct_name=definition["distribution"], cache=cache, pypi=pypi)
            for item in packages
        ]
        for component in components:
            component["known_advisory_ids"] = advisories[(component["name"], component["version"])]
        components.sort(key=lambda item: (item["name"], item["version"]))
        candidates.append(
            {
                "blockers": definition["blockers"],
                "components": components,
                "distribution": definition["distribution"],
                "extras": definition["extras"],
                "id": definition["id"],
                "import_name": definition["import_name"],
                "installation_eligible": False,
                "requested_requirement": f"{definition['distribution']}=={definition['version']}",
                "scratch_lock": {
                    "external_component_count": len(packages),
                    "requires_python": lock["requires-python"],
                    "sha256": _sha256_file(lock_path),
                },
                "status": definition["status"],
                "tier": definition["tier"],
                "version": definition["version"],
            }
        )

    manifest: dict[str, Any] = {
        "advisory_snapshot": {
            "provider": "OSV",
            "queried_at": generated_at,
            "query_count": len(identities),
            "request_sha256": _sha256_bytes(osv_payload),
            "response_sha256": _sha256_bytes(osv_body),
            "service_url": "https://api.osv.dev/v1/querybatch",
            "tool": {
                "name": "audit_pdf_parser_dependencies.py",
                "schema_version": SCHEMA_VERSION,
                "sha256": _sha256_file(Path(__file__)),
            },
        },
        "baseline": {
            "package_count": 42,
            "pyproject_sha256": _sha256_file(ROOT / "pyproject.toml"),
            "uv_lock_sha256": _sha256_file(ROOT / "uv.lock"),
            "uv_lock_version": 1,
            "uv_version": "0.5.23",
        },
        "candidates": candidates,
        "generated_at": generated_at,
        "manifest_sha256": "",
        "policy": {
            "accepted_registry_prefixes": [
                "https://pypi.org/simple",
                "https://files.pythonhosted.org/",
            ],
            "block_on": [
                "critical_or_high_unmitigated_advisory",
                "license_evidence_incomplete",
                "model_artifacts_unreviewed",
                "remote_code_supported",
                "runtime_model_download",
                "source_distribution_requires_build",
                "unsafe_deserialization_surface",
            ],
            "requires_explicit_approval": True,
            "wheel_only": True,
        },
        "schema_version": SCHEMA_VERSION,
        "target_environment": {
            "implementation": "CPython",
            "machine": "arm64",
            "platform": "macOS",
            "python_version": "3.12.13",
            "service_scope": "document-worker-only",
        },
    }
    manifest["manifest_sha256"] = _manifest_digest(manifest)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(json.dumps(manifest, indent=2, sort_keys=True).encode() + b"\n")
    print(f"captured {output} ({manifest['manifest_sha256']})")


def _load_approval(path: Path) -> dict[str, Any]:
    text = path.read_text()
    begin = "<!-- RSI_ATLAS_PDF_PARSER_APPROVAL_BEGIN -->"
    end = "<!-- RSI_ATLAS_PDF_PARSER_APPROVAL_END -->"
    _require(
        text.count(begin) == 1 and text.count(end) == 1, "approval must contain one machine record"
    )
    payload = text.split(begin, 1)[1].split(end, 1)[0].strip()
    _require(
        payload.startswith("```json\n") and payload.endswith("\n```"),
        "approval record must be JSON fenced",
    )
    return json.loads(payload.removeprefix("```json\n").removesuffix("\n```"))


def verify(manifest_path: Path, approval_path: Path, sbom_path: Path | None) -> None:
    manifest = json.loads(manifest_path.read_text())
    _require(manifest.get("schema_version") == SCHEMA_VERSION, "unsupported governance schema")
    _require(
        set(manifest)
        == {
            "advisory_snapshot",
            "baseline",
            "candidates",
            "generated_at",
            "manifest_sha256",
            "policy",
            "schema_version",
            "target_environment",
        },
        "manifest keys changed",
    )
    _require(
        UTC_RE.fullmatch(manifest["generated_at"]) is not None,
        "generated_at must be second-precision UTC",
    )
    _require(
        SHA256_RE.fullmatch(manifest["manifest_sha256"]) is not None, "manifest hash is invalid"
    )
    _require(
        manifest["manifest_sha256"] == _manifest_digest(manifest),
        "manifest hash does not match content",
    )
    baseline = manifest["baseline"]
    _require(
        baseline["pyproject_sha256"] == _sha256_file(ROOT / "pyproject.toml"),
        "pyproject baseline changed",
    )
    _require(
        baseline["uv_lock_sha256"] == _sha256_file(ROOT / "uv.lock"), "accepted uv.lock changed"
    )
    expected = {item["id"]: item for item in CANDIDATES}
    _require(
        [item["id"] for item in manifest["candidates"]] == list(expected),
        "candidate order or identities changed",
    )
    for candidate in manifest["candidates"]:
        definition = expected[candidate["id"]]
        _require(
            candidate["version"] == definition["version"],
            f"candidate version changed: {candidate['id']}",
        )
        _require(
            candidate["extras"] == definition["extras"],
            f"candidate extras changed: {candidate['id']}",
        )
        _require(
            candidate["scratch_lock"]["sha256"] == definition["lock_sha256"],
            f"scratch lock changed: {candidate['id']}",
        )
        _require(
            len(candidate["components"]) == definition["component_count"],
            f"component inventory is incomplete: {candidate['id']}",
        )
        _require(
            candidate["installation_eligible"] is False,
            "unapproved manifest cannot install dependencies",
        )
        _require(
            candidate["blockers"] == sorted(set(candidate["blockers"])),
            f"blockers must be sorted: {candidate['id']}",
        )
        purls: set[str] = set()
        for component in candidate["components"]:
            _require(component["purl"] not in purls, f"duplicate purl: {component['purl']}")
            purls.add(component["purl"])
            _require(
                component["license_expression"]
                or component["license_evidence_status"] != "reviewed_wheel_metadata",
                f"missing reviewed license: {component['purl']}",
            )
            _require(
                isinstance(component["known_advisory_ids"], list),
                f"missing advisory result: {component['purl']}",
            )
            if component["license_evidence_status"] == "reviewed_wheel_metadata":
                _require(
                    component["selected_wheel_license_files"],
                    f"missing license text evidence: {component['purl']}",
                )
            for license_file in component["selected_wheel_license_files"]:
                _require(
                    SHA256_RE.fullmatch(license_file["sha256"]) is not None,
                    f"bad license text hash: {component['purl']}",
                )
            for artifact in component["artifacts"]:
                _require(
                    SHA256_RE.fullmatch(artifact["sha256"]) is not None,
                    f"bad artifact hash: {artifact['filename']}",
                )
                _require(artifact["size_bytes"] > 0, f"empty artifact: {artifact['filename']}")
                _require(
                    artifact["source_url"].startswith("https://files.pythonhosted.org/"),
                    f"unapproved artifact host: {artifact['source_url']}",
                )
        _require(
            sum(component["direct"] for component in candidate["components"]) == 1,
            f"candidate must have one direct component: {candidate['id']}",
        )

    snapshot = manifest["advisory_snapshot"]
    unique_purls = {
        component["purl"]
        for candidate in manifest["candidates"]
        for component in candidate["components"]
    }
    _require(
        snapshot["provider"] == "OSV" and snapshot["query_count"] == len(unique_purls),
        "advisory inventory changed",
    )
    _require(UTC_RE.fullmatch(snapshot["queried_at"]) is not None, "advisory time is invalid")
    _require(
        SHA256_RE.fullmatch(snapshot["request_sha256"]) is not None,
        "advisory request hash is invalid",
    )
    _require(
        SHA256_RE.fullmatch(snapshot["response_sha256"]) is not None,
        "advisory response hash is invalid",
    )
    _require(
        snapshot["tool"]["sha256"] == _sha256_file(Path(__file__)),
        "advisory capture tool changed",
    )

    approval = _load_approval(approval_path)
    expected_approval_keys = {
        "accepted_exceptions",
        "actor_id",
        "approval_sha256",
        "authority",
        "blocked_candidates",
        "decided_at",
        "decision",
        "manifest_sha256",
        "model_artifacts",
        "proposed_candidates",
        "rollback",
        "schema_version",
        "target_environment",
    }
    _require(set(approval) == expected_approval_keys, "approval keys changed")
    _require(approval["schema_version"] == APPROVAL_SCHEMA, "unsupported approval schema")
    _require(
        SHA256_RE.fullmatch(approval["approval_sha256"]) is not None,
        "approval hash is invalid",
    )
    _require(
        approval["approval_sha256"] == _approval_digest(approval),
        "approval hash does not match content",
    )
    _require(
        approval["manifest_sha256"] == manifest["manifest_sha256"],
        "approval is not bound to this manifest",
    )
    _require(approval["accepted_exceptions"] == [], "unreviewed approval exception")
    _require(approval["model_artifacts"] == [], "unreviewed model artifact")
    proposed_ids = [item["id"] for item in approval["proposed_candidates"]]
    _require(
        proposed_ids == ["pypdf-base", "pdfminer-six-base"],
        "approval candidate set changed",
    )
    manifest_candidates = {item["id"]: item for item in manifest["candidates"]}
    for proposal in approval["proposed_candidates"]:
        candidate = manifest_candidates[proposal["id"]]
        expected_components = [component["purl"] for component in candidate["components"]]
        expected_artifacts = sorted(
            component["selected_target_artifact"]["sha256"]
            for component in candidate["components"]
            if component["selected_target_artifact"] is not None
        )
        _require(
            proposal["requirement"] == candidate["requested_requirement"],
            f"approval requirement changed: {proposal['id']}",
        )
        _require(
            proposal["extras"] == candidate["extras"],
            f"approval extras changed: {proposal['id']}",
        )
        _require(
            proposal["components"] == expected_components,
            f"approval components changed: {proposal['id']}",
        )
        _require(
            proposal["artifact_sha256"] == expected_artifacts,
            f"approval artifacts changed: {proposal['id']}",
        )
    _require(
        approval["blocked_candidates"]
        == [
            {
                "id": "docling-standard-benchmark",
                "reason": "blocked_dependency_governance",
                "requirement": "docling==2.113.0",
            }
        ],
        "blocked candidate set changed",
    )
    _require(
        approval["target_environment"]
        == {
            key: manifest["target_environment"][key]
            for key in ("implementation", "machine", "platform", "python_version")
        },
        "approval target environment changed",
    )
    _require(
        approval["decision"] in {"pending_user_approval", "approved"}, "invalid approval decision"
    )
    if approval["decision"] == "pending_user_approval":
        _require(
            approval["actor_id"] is None and approval["decided_at"] is None,
            "pending approval cannot name an actor or time",
        )
    else:
        _require(approval["actor_id"], "approved record requires a stable actor id")
        _require(
            UTC_RE.fullmatch(approval["decided_at"]) is not None,
            "approved record requires UTC time",
        )

    if sbom_path is not None:
        components_by_purl = {
            component["purl"]: component
            for candidate in manifest["candidates"]
            for component in candidate["components"]
        }
        components = [components_by_purl[purl] for purl in sorted(components_by_purl)]
        sbom = {
            "bomFormat": "CycloneDX",
            "components": [
                {
                    "bom-ref": component["purl"],
                    "licenses": [{"expression": component["license_expression"] or "NOASSERTION"}],
                    "name": component["name"],
                    "purl": component["purl"],
                    "type": "library",
                    "version": component["version"],
                }
                for component in components
            ],
            "metadata": {
                "properties": [
                    {"name": "rsi-atlas:manifest-sha256", "value": manifest["manifest_sha256"]}
                ]
            },
            "specVersion": "1.6",
            "version": 1,
        }
        sbom_path.parent.mkdir(parents=True, exist_ok=True)
        sbom_path.write_bytes(json.dumps(sbom, indent=2, sort_keys=True).encode() + b"\n")
    print(f"verified {manifest_path} ({manifest['manifest_sha256']})")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    capture_parser = subparsers.add_parser(
        "capture", help="networked capture from owner-private scratch locks"
    )
    capture_parser.add_argument("--scratch-root", type=Path, required=True)
    capture_parser.add_argument("--output", type=Path, default=DEFAULT_MANIFEST)
    verify_parser = subparsers.add_parser(
        "verify", help="offline verification of committed governance evidence"
    )
    verify_parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    verify_parser.add_argument("--approval", type=Path, default=DEFAULT_APPROVAL)
    verify_parser.add_argument("--sbom-out", type=Path, default=DEFAULT_SBOM)
    args = parser.parse_args()
    try:
        if args.command == "capture":
            capture(args.scratch_root.resolve(), args.output.resolve())
        else:
            verify(args.manifest.resolve(), args.approval.resolve(), args.sbom_out.resolve())
    except (GovernanceError, OSError, json.JSONDecodeError, tomllib.TOMLDecodeError) as error:
        print(f"dependency governance failed: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
