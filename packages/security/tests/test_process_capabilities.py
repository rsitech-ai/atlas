from __future__ import annotations

import json
from pathlib import Path

import pytest
from rsi_atlas_security import (
    DataClass,
    ManifestValidationError,
    ProcessRole,
    load_process_capability_manifest,
    parse_process_capability_manifest,
)

MANIFEST_PATH = Path("infra/security/process-capabilities.json")
ROLE_CAPABILITIES = {
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
PROHIBITED_CAPABILITIES = (
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
)
COLLECTOR_PRIVATE_DATA = (
    "private_pdfs",
    "analyst_notes",
    "reports",
    "prompts",
    "traces",
    "codex_worktrees",
    "private_artifact_root",
    "private_database_root",
)
NO_KEYCHAIN_ROLES = (
    ProcessRole.DOCUMENT_WORKER,
    ProcessRole.MODEL_WORKER,
    ProcessRole.EVALUATION_WORKER,
    ProcessRole.CODEX_CONTROLLER,
)
APPROVED_READS = {
    ProcessRole.API: {"reports", "traces"},
    ProcessRole.ENGINE: {"indexes", "features", "evaluations"},
    ProcessRole.DOCUMENT_WORKER: {"private_pdfs"},
    ProcessRole.MODEL_WORKER: {"indexes", "prompts"},
    ProcessRole.DATA_WORKER: {"public_sources", "chain_data", "quarantine"},
    ProcessRole.EVALUATION_WORKER: {"features", "reports"},
    ProcessRole.COLLECTOR: {"public_sources", "chain_data"},
    ProcessRole.EXPORTER: {"reports"},
    ProcessRole.CODEX_CONTROLLER: {"codex_worktrees"},
}
APPROVED_WRITES = {
    ProcessRole.API: set(),
    ProcessRole.ENGINE: {"traces"},
    ProcessRole.DOCUMENT_WORKER: {"indexes"},
    ProcessRole.MODEL_WORKER: {"features"},
    ProcessRole.DATA_WORKER: {"indexes"},
    ProcessRole.EVALUATION_WORKER: {"evaluations"},
    ProcessRole.COLLECTOR: {"quarantine"},
    ProcessRole.EXPORTER: set(),
    ProcessRole.CODEX_CONTROLLER: set(),
}


def _process(role: ProcessRole) -> dict[str, object]:
    return {
        "role": role.value,
        "read_data_classes": sorted(APPROVED_READS[role]),
        "write_data_classes": sorted(APPROVED_WRITES[role]),
        "keychain_access": role is ProcessRole.COLLECTOR,
        "network_destinations": [],
        "subprocess_authority": role is ProcessRole.CODEX_CONTROLLER,
        "shell_authority": False,
        "capabilities": [ROLE_CAPABILITIES[role]],
    }


def _manifest(*processes: dict[str, object]) -> str:
    return json.dumps({"schema_version": "1.0.0", "processes": list(processes)})


def _replace(process: dict[str, object], **changes: object) -> dict[str, object]:
    return {**process, **changes}


def test_shipped_manifest_is_complete_and_deterministic() -> None:
    capabilities = load_process_capability_manifest(MANIFEST_PATH)

    assert tuple(capability.role for capability in capabilities) == tuple(ProcessRole)
    assert all(capability.shell_authority is False for capability in capabilities)
    assert all(capability.prohibited_capabilities == frozenset() for capability in capabilities)


def test_manifest_values_are_typed_and_frozen() -> None:
    capability = parse_process_capability_manifest(_manifest(_process(ProcessRole.API)))[0]

    assert capability.role is ProcessRole.API
    assert capability.read_data_classes == frozenset({DataClass.REPORTS, DataClass.TRACES})
    assert capability.capabilities == frozenset({"api_control"})
    with pytest.raises(AttributeError):
        capability.role = ProcessRole.COLLECTOR  # type: ignore[misc]


@pytest.mark.parametrize("root_key", ["unknown", "profile", "default_role"])
def test_manifest_rejects_unknown_root_keys(root_key: str) -> None:
    payload = json.loads(_manifest(_process(ProcessRole.API)))
    payload[root_key] = True

    with pytest.raises(ManifestValidationError, match="unknown manifest key"):
        parse_process_capability_manifest(json.dumps(payload))


@pytest.mark.parametrize("process_key", ["unknown", "environment", "entitlements"])
def test_manifest_rejects_unknown_process_keys(process_key: str) -> None:
    process = _process(ProcessRole.API)
    process[process_key] = True

    with pytest.raises(ManifestValidationError, match="unknown process key"):
        parse_process_capability_manifest(_manifest(process))


def test_manifest_rejects_duplicate_json_keys() -> None:
    raw = '{"schema_version":"1.0.0","schema_version":"2.0.0","processes":[]}'

    with pytest.raises(ManifestValidationError, match="duplicate JSON key"):
        parse_process_capability_manifest(raw)


def test_manifest_rejects_duplicate_roles() -> None:
    process = _process(ProcessRole.API)

    with pytest.raises(ManifestValidationError, match="duplicate process role"):
        parse_process_capability_manifest(_manifest(process, process))


def test_manifest_rejects_unknown_role() -> None:
    process = _replace(_process(ProcessRole.API), role="atlas-unknown")

    with pytest.raises(ManifestValidationError, match="unknown process role"):
        parse_process_capability_manifest(_manifest(process))


@pytest.mark.parametrize("field", ["capabilities", "read_data_classes", "network_destinations"])
def test_manifest_rejects_duplicate_list_entries(field: str) -> None:
    process = _process(ProcessRole.API)
    value = process[field]
    assert isinstance(value, list)
    item = (
        "api_control"
        if field == "capabilities"
        else ("public_sources" if field == "read_data_classes" else "http://127.0.0.1:8765")
    )
    process[field] = [item, item]

    with pytest.raises(ManifestValidationError, match="duplicate"):
        parse_process_capability_manifest(_manifest(process))


def test_manifest_rejects_unknown_capability_and_data_class() -> None:
    unknown_capability = _replace(
        _process(ProcessRole.API), capabilities=["unrecognized_capability"]
    )
    unknown_data = _replace(_process(ProcessRole.API), read_data_classes=["unrecognized_data"])

    with pytest.raises(ManifestValidationError, match="unknown capability"):
        parse_process_capability_manifest(_manifest(unknown_capability))
    with pytest.raises(ManifestValidationError, match="unknown data class"):
        parse_process_capability_manifest(_manifest(unknown_data))


@pytest.mark.parametrize("private_data", COLLECTOR_PRIVATE_DATA)
def test_collector_cannot_read_private_data(private_data: str) -> None:
    collector = _replace(_process(ProcessRole.COLLECTOR), read_data_classes=[private_data])

    with pytest.raises(ManifestValidationError, match="collector private data"):
        parse_process_capability_manifest(_manifest(collector))


@pytest.mark.parametrize("private_data", COLLECTOR_PRIVATE_DATA)
def test_collector_cannot_write_private_data(private_data: str) -> None:
    collector = _replace(_process(ProcessRole.COLLECTOR), write_data_classes=[private_data])

    with pytest.raises(ManifestValidationError, match="collector private data"):
        parse_process_capability_manifest(_manifest(collector))


@pytest.mark.parametrize("role", tuple(ProcessRole))
@pytest.mark.parametrize("field", ["read_data_classes", "write_data_classes"])
def test_each_role_rejects_data_grants_outside_approved_matrix(
    role: ProcessRole,
    field: str,
) -> None:
    approved = APPROVED_READS[role] if field == "read_data_classes" else APPROVED_WRITES[role]
    unapproved = next(data.value for data in DataClass if data.value not in approved)
    process = _replace(_process(role), **{field: [unapproved]})

    with pytest.raises(ManifestValidationError, match="data grant"):
        parse_process_capability_manifest(_manifest(process))


@pytest.mark.parametrize("role", NO_KEYCHAIN_ROLES)
def test_untrusted_and_engineering_workers_cannot_access_keychain(role: ProcessRole) -> None:
    process = _replace(_process(role), keychain_access=True)

    with pytest.raises(ManifestValidationError, match="Keychain"):
        parse_process_capability_manifest(_manifest(process))


@pytest.mark.parametrize(
    "role",
    tuple(role for role in ProcessRole if role is not ProcessRole.COLLECTOR),
)
def test_keychain_grant_is_rejected_outside_approved_role(role: ProcessRole) -> None:
    process = _replace(_process(role), keychain_access=True)

    with pytest.raises(ManifestValidationError, match="Keychain"):
        parse_process_capability_manifest(_manifest(process))


def test_collector_accepts_exact_keychain_network_and_data_matrix() -> None:
    collector = _replace(
        _process(ProcessRole.COLLECTOR),
        read_data_classes=["public_sources", "chain_data"],
        write_data_classes=["quarantine"],
        keychain_access=True,
        network_destinations=["https://rpc.example:443"],
    )

    parsed = parse_process_capability_manifest(
        _manifest(collector),
        expected_collector_destinations=["https://rpc.example:443"],
    )[0]

    assert parsed.keychain_access is True
    assert parsed.network_destinations == ("https://rpc.example:443",)


@pytest.mark.parametrize(
    "role,field",
    [
        (ProcessRole.COLLECTOR, "keychain_access"),
        (ProcessRole.CODEX_CONTROLLER, "subprocess_authority"),
    ],
)
def test_required_role_authority_cannot_be_removed(
    role: ProcessRole,
    field: str,
) -> None:
    process = _replace(_process(role), **{field: False})

    with pytest.raises(ManifestValidationError, match="exact"):
        parse_process_capability_manifest(_manifest(process))


@pytest.mark.parametrize("role", tuple(ProcessRole))
@pytest.mark.parametrize("field", ["read_data_classes", "write_data_classes"])
def test_each_role_rejects_missing_data_grants_from_exact_matrix(
    role: ProcessRole,
    field: str,
) -> None:
    process = _process(role)
    values = process[field]
    assert isinstance(values, list)
    if values:
        process[field] = values[:-1]
    else:
        process[field] = [DataClass.PUBLIC_SOURCES.value]

    with pytest.raises(ManifestValidationError, match="exact data grant matrix"):
        parse_process_capability_manifest(_manifest(process))


def test_collector_network_destinations_must_equal_explicit_expected_allowlist() -> None:
    collector = _replace(
        _process(ProcessRole.COLLECTOR),
        network_destinations=["https://rpc.example:443"],
    )
    payload = _manifest(collector)

    with pytest.raises(ManifestValidationError, match="collector network destination matrix"):
        parse_process_capability_manifest(payload)
    with pytest.raises(ManifestValidationError, match="collector network destination matrix"):
        parse_process_capability_manifest(
            payload,
            expected_collector_destinations=["https://other.example:443"],
        )
    with pytest.raises(ManifestValidationError, match="collector network destination matrix"):
        parse_process_capability_manifest(
            _manifest(_process(ProcessRole.COLLECTOR)),
            expected_collector_destinations=["https://rpc.example:443"],
        )


def test_expected_collector_allowlist_rejects_canonical_duplicates() -> None:
    with pytest.raises(ManifestValidationError, match="duplicate expected collector"):
        parse_process_capability_manifest(
            _manifest(_process(ProcessRole.COLLECTOR)),
            expected_collector_destinations=[
                "https://RPC.EXAMPLE:443",
                "HTTPS://rpc.example:443",
            ],
        )


def test_shipped_loader_defaults_offline_and_accepts_only_its_exact_allowlist() -> None:
    capabilities = load_process_capability_manifest(
        MANIFEST_PATH,
        expected_collector_destinations=(),
    )

    assert (
        next(
            capability for capability in capabilities if capability.role is ProcessRole.COLLECTOR
        ).network_destinations
        == ()
    )
    with pytest.raises(ManifestValidationError, match="collector network destination matrix"):
        load_process_capability_manifest(
            MANIFEST_PATH,
            expected_collector_destinations=["https://rpc.example:443"],
        )


@pytest.mark.parametrize("role", tuple(ProcessRole))
@pytest.mark.parametrize("capability", PROHIBITED_CAPABILITIES)
def test_prohibited_authority_is_rejected_for_every_role(
    role: ProcessRole,
    capability: str,
) -> None:
    process = _replace(_process(role), capabilities=[capability])

    with pytest.raises(ManifestValidationError, match="prohibited capability"):
        parse_process_capability_manifest(_manifest(process))


@pytest.mark.parametrize("role", tuple(ProcessRole))
def test_shell_authority_is_rejected_for_every_role(role: ProcessRole) -> None:
    process = _replace(_process(role), shell_authority=True)

    with pytest.raises(ManifestValidationError, match="shell authority"):
        parse_process_capability_manifest(_manifest(process))


@pytest.mark.parametrize(
    "role",
    tuple(role for role in ProcessRole if role is not ProcessRole.CODEX_CONTROLLER),
)
def test_subprocess_authority_is_rejected_outside_codex(role: ProcessRole) -> None:
    process = _replace(_process(role), subprocess_authority=True)

    with pytest.raises(ManifestValidationError, match="subprocess authority"):
        parse_process_capability_manifest(_manifest(process))


@pytest.mark.parametrize(
    "role",
    tuple(role for role in ProcessRole if role is not ProcessRole.COLLECTOR),
)
def test_remote_destination_is_rejected_outside_collector(role: ProcessRole) -> None:
    process = _replace(_process(role), network_destinations=["https://rpc.example:443"])

    with pytest.raises(ManifestValidationError, match="remote network"):
        parse_process_capability_manifest(_manifest(process))


@pytest.mark.parametrize(
    "destination",
    [
        "https://*.example.com:443",
        "https://user@example.com:443",
        "https://example.com",
        "https://example.com:443/path",
        "https://127.0.0.1:443",
        "ftp://example.com:21",
        "localhost:8765",
    ],
)
def test_collector_destination_uses_strict_remote_origin_rules(destination: str) -> None:
    process = _replace(_process(ProcessRole.COLLECTOR), network_destinations=[destination])

    with pytest.raises(ManifestValidationError, match="network destination"):
        parse_process_capability_manifest(_manifest(process))


def test_role_capability_mismatch_is_rejected_as_contradictory() -> None:
    process = _replace(_process(ProcessRole.API), capabilities=["remote_collection"])

    with pytest.raises(ManifestValidationError, match="contradictory"):
        parse_process_capability_manifest(_manifest(process))


@pytest.mark.parametrize(
    "field,value",
    [
        ("role", None),
        ("read_data_classes", None),
        ("keychain_access", 1),
        ("subprocess_authority", "false"),
        ("capabilities", "api_control"),
    ],
)
def test_manifest_rejects_missing_or_wrongly_typed_fields(field: str, value: object) -> None:
    process = _process(ProcessRole.API)
    if value is None:
        del process[field]
    else:
        process[field] = value

    with pytest.raises(ManifestValidationError, match="process manifest"):
        parse_process_capability_manifest(_manifest(process))


def test_data_class_enum_is_closed() -> None:
    assert DataClass("public_sources") is DataClass.PUBLIC_SOURCES
    with pytest.raises(ValueError):
        DataClass("secret_unknown")
