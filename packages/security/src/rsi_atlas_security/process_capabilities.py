from __future__ import annotations

import json
from collections.abc import Iterable
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any

from rsi_atlas_security.network_policy import ProcessRole, canonical_remote_origin


class ManifestValidationError(ValueError):
    pass


class DataClass(StrEnum):
    PUBLIC_SOURCES = "public_sources"
    CHAIN_DATA = "chain_data"
    QUARANTINE = "quarantine"
    INDEXES = "indexes"
    FEATURES = "features"
    EVALUATIONS = "evaluations"
    PRIVATE_PDFS = "private_pdfs"
    ANALYST_NOTES = "analyst_notes"
    REPORTS = "reports"
    PROMPTS = "prompts"
    TRACES = "traces"
    CODEX_WORKTREES = "codex_worktrees"
    PRIVATE_ARTIFACT_ROOT = "private_artifact_root"
    PRIVATE_DATABASE_ROOT = "private_database_root"


ROLE_CAPABILITY = {
    ProcessRole.API: "api_control",
    ProcessRole.ENGINE: "engine_control",
    ProcessRole.DOCUMENT_WORKER: "document_parse",
    ProcessRole.MODEL_WORKER: "model_inference",
    ProcessRole.DATA_WORKER: "data_transform",
    ProcessRole.EVALUATION_WORKER: "evaluation_run",
    ProcessRole.COLLECTOR: "remote_collection",
    ProcessRole.EXPORTER: "candidate_export",
    ProcessRole.CODEX_CONTROLLER: "codex_patch",
}
PROHIBITED_CAPABILITIES = frozenset(
    {
        "trading",
        "exchange_account",
        "wallet",
        "custody",
        "blockchain_signing",
        "signing",
        "private_key",
        "unrestricted_shell",
        "policy_mutation",
        "model_promotion",
        "evaluation_promotion",
        "publication",
        "merge",
        "push",
    }
)
KNOWN_CAPABILITIES = frozenset(ROLE_CAPABILITY.values()) | PROHIBITED_CAPABILITIES
COLLECTOR_PRIVATE_DATA = frozenset(
    {
        DataClass.PRIVATE_PDFS,
        DataClass.ANALYST_NOTES,
        DataClass.REPORTS,
        DataClass.PROMPTS,
        DataClass.TRACES,
        DataClass.CODEX_WORKTREES,
        DataClass.PRIVATE_ARTIFACT_ROOT,
        DataClass.PRIVATE_DATABASE_ROOT,
    }
)
APPROVED_READ_DATA = {
    ProcessRole.API: frozenset({DataClass.REPORTS, DataClass.TRACES}),
    ProcessRole.ENGINE: frozenset({DataClass.INDEXES, DataClass.FEATURES, DataClass.EVALUATIONS}),
    ProcessRole.DOCUMENT_WORKER: frozenset({DataClass.PRIVATE_PDFS}),
    ProcessRole.MODEL_WORKER: frozenset({DataClass.INDEXES, DataClass.PROMPTS}),
    ProcessRole.DATA_WORKER: frozenset(
        {DataClass.PUBLIC_SOURCES, DataClass.CHAIN_DATA, DataClass.QUARANTINE}
    ),
    ProcessRole.EVALUATION_WORKER: frozenset({DataClass.FEATURES, DataClass.REPORTS}),
    ProcessRole.COLLECTOR: frozenset({DataClass.PUBLIC_SOURCES, DataClass.CHAIN_DATA}),
    ProcessRole.EXPORTER: frozenset({DataClass.REPORTS}),
    ProcessRole.CODEX_CONTROLLER: frozenset({DataClass.CODEX_WORKTREES}),
}
APPROVED_WRITE_DATA = {
    ProcessRole.API: frozenset(),
    ProcessRole.ENGINE: frozenset({DataClass.TRACES}),
    ProcessRole.DOCUMENT_WORKER: frozenset({DataClass.INDEXES}),
    ProcessRole.MODEL_WORKER: frozenset({DataClass.FEATURES}),
    ProcessRole.DATA_WORKER: frozenset({DataClass.INDEXES}),
    ProcessRole.EVALUATION_WORKER: frozenset({DataClass.EVALUATIONS}),
    ProcessRole.COLLECTOR: frozenset({DataClass.QUARANTINE}),
    ProcessRole.EXPORTER: frozenset(),
    ProcessRole.CODEX_CONTROLLER: frozenset(),
}
ROOT_KEYS = frozenset({"schema_version", "processes"})
PROCESS_KEYS = frozenset(
    {
        "role",
        "read_data_classes",
        "write_data_classes",
        "keychain_access",
        "network_destinations",
        "subprocess_authority",
        "shell_authority",
        "capabilities",
    }
)


@dataclass(frozen=True, slots=True)
class ProcessCapability:
    role: ProcessRole
    read_data_classes: frozenset[DataClass]
    write_data_classes: frozenset[DataClass]
    keychain_access: bool
    network_destinations: tuple[str, ...]
    subprocess_authority: bool
    shell_authority: bool
    capabilities: frozenset[str]
    prohibited_capabilities: frozenset[str]


def _strict_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ManifestValidationError("duplicate JSON key in capability manifest")
        result[key] = value
    return result


def _strict_string_list(value: object, *, field: str) -> list[str]:
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise ManifestValidationError("process manifest field types are invalid")
    if len(value) != len(set(value)):
        raise ManifestValidationError(f"duplicate {field} entry")
    return value


def _parse_data_classes(value: object) -> frozenset[DataClass]:
    values = _strict_string_list(value, field="data class")
    try:
        return frozenset(DataClass(item) for item in values)
    except ValueError as error:
        raise ManifestValidationError("unknown data class in process manifest") from error


def _parse_capabilities(value: object) -> frozenset[str]:
    capabilities = frozenset(_strict_string_list(value, field="capability"))
    unknown = capabilities - KNOWN_CAPABILITIES
    if unknown:
        raise ManifestValidationError("unknown capability in process manifest")
    prohibited = capabilities & PROHIBITED_CAPABILITIES
    if prohibited:
        raise ManifestValidationError("prohibited capability in process manifest")
    return capabilities


def _parse_remote_destinations(value: object, *, role: ProcessRole) -> tuple[str, ...]:
    values = _strict_string_list(value, field="network destination")
    destinations: list[str] = []
    for item in values:
        try:
            destination = canonical_remote_origin(item)
        except ValueError as error:
            raise ManifestValidationError(
                "invalid network destination in process manifest"
            ) from error
        if destination in destinations:
            raise ManifestValidationError("duplicate canonical network destination")
        destinations.append(destination)
    if destinations and role is not ProcessRole.COLLECTOR:
        raise ManifestValidationError("process role has prohibited remote network destination")
    return tuple(destinations)


def _parse_process(
    raw: object,
    *,
    expected_collector_destinations: frozenset[str],
) -> ProcessCapability:
    if not isinstance(raw, dict):
        raise ManifestValidationError("process manifest entry must be an object")
    keys = frozenset(raw)
    unknown = keys - PROCESS_KEYS
    if unknown:
        raise ManifestValidationError("unknown process key in capability manifest")
    if keys != PROCESS_KEYS:
        raise ManifestValidationError("process manifest is missing required fields")
    try:
        raw_role = raw["role"]
        if not isinstance(raw_role, str):
            raise TypeError
        role = ProcessRole(raw_role)
    except (TypeError, ValueError) as error:
        raise ManifestValidationError("unknown process role in capability manifest") from error
    keychain_access = raw["keychain_access"]
    subprocess_authority = raw["subprocess_authority"]
    shell_authority = raw["shell_authority"]
    if not all(
        isinstance(value, bool)
        for value in (keychain_access, subprocess_authority, shell_authority)
    ):
        raise ManifestValidationError("process manifest field types are invalid")
    reads = _parse_data_classes(raw["read_data_classes"])
    writes = _parse_data_classes(raw["write_data_classes"])
    if reads & writes:
        raise ManifestValidationError("process manifest contains contradictory data grants")
    if role is ProcessRole.COLLECTOR and (reads | writes) & COLLECTOR_PRIVATE_DATA:
        raise ManifestValidationError("collector private data grant is prohibited")
    if reads != APPROVED_READ_DATA[role] or writes != APPROVED_WRITE_DATA[role]:
        raise ManifestValidationError("process manifest violates exact data grant matrix")
    capabilities = _parse_capabilities(raw["capabilities"])
    if capabilities != frozenset({ROLE_CAPABILITY[role]}):
        raise ManifestValidationError("process manifest contains contradictory capability grants")
    if keychain_access is not (role is ProcessRole.COLLECTOR):
        raise ManifestValidationError("process manifest violates exact Keychain access matrix")
    if shell_authority:
        raise ManifestValidationError("shell authority is prohibited")
    if subprocess_authority is not (role is ProcessRole.CODEX_CONTROLLER):
        raise ManifestValidationError("process manifest violates exact subprocess authority matrix")
    destinations = _parse_remote_destinations(raw["network_destinations"], role=role)
    expected_destinations = (
        expected_collector_destinations if role is ProcessRole.COLLECTOR else frozenset()
    )
    if frozenset(destinations) != expected_destinations:
        raise ManifestValidationError(
            "process manifest violates exact collector network destination matrix"
        )
    return ProcessCapability(
        role=role,
        read_data_classes=reads,
        write_data_classes=writes,
        keychain_access=keychain_access,
        network_destinations=destinations,
        subprocess_authority=subprocess_authority,
        shell_authority=shell_authority,
        capabilities=capabilities,
        prohibited_capabilities=frozenset(),
    )


def _expected_collector_destinations(values: Iterable[str]) -> frozenset[str]:
    if isinstance(values, (str, bytes)):
        raise ManifestValidationError("expected collector destination collection is invalid")
    canonical: set[str] = set()
    try:
        for value in values:
            destination = canonical_remote_origin(value)
            if destination in canonical:
                raise ManifestValidationError("duplicate expected collector destination")
            canonical.add(destination)
    except ManifestValidationError:
        raise
    except (TypeError, ValueError) as error:
        raise ManifestValidationError("invalid expected collector destination") from error
    return frozenset(canonical)


def parse_process_capability_manifest(
    payload: str,
    *,
    expected_collector_destinations: Iterable[str] = (),
) -> tuple[ProcessCapability, ...]:
    expected_destinations = _expected_collector_destinations(expected_collector_destinations)
    try:
        raw = json.loads(payload, object_pairs_hook=_strict_object)
    except ManifestValidationError:
        raise
    except (json.JSONDecodeError, RecursionError) as error:
        raise ManifestValidationError("capability manifest JSON is invalid") from error
    if not isinstance(raw, dict):
        raise ManifestValidationError("capability manifest root must be an object")
    keys = frozenset(raw)
    unknown = keys - ROOT_KEYS
    if unknown:
        raise ManifestValidationError("unknown manifest key in capability manifest")
    if keys != ROOT_KEYS or raw.get("schema_version") != "1.0.0":
        raise ManifestValidationError("capability manifest schema is invalid")
    processes = raw.get("processes")
    if not isinstance(processes, list):
        raise ManifestValidationError("capability manifest processes must be a list")
    parsed: list[ProcessCapability] = []
    seen_roles: set[ProcessRole] = set()
    for raw_process in processes:
        process = _parse_process(
            raw_process,
            expected_collector_destinations=expected_destinations,
        )
        if process.role in seen_roles:
            raise ManifestValidationError("duplicate process role in capability manifest")
        seen_roles.add(process.role)
        parsed.append(process)
    return tuple(parsed)


def load_process_capability_manifest(
    path: Path,
    *,
    expected_collector_destinations: Iterable[str] = (),
) -> tuple[ProcessCapability, ...]:
    try:
        payload = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as error:
        raise ManifestValidationError("capability manifest could not be read") from error
    capabilities = parse_process_capability_manifest(
        payload,
        expected_collector_destinations=expected_collector_destinations,
    )
    if tuple(capability.role for capability in capabilities) != tuple(ProcessRole):
        raise ManifestValidationError(
            "shipped capability manifest roles are incomplete or unordered"
        )
    return capabilities
