from pathlib import Path
from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError
from rsi_atlas_contracts.models import ModelArtifact, ModelCapability, ModelLifecycle


def test_model_contract_rejects_coercion_and_unknown_fields(tmp_path: Path) -> None:
    values = dict(
        artifact_id=uuid4(),
        sha256="a" * 64,
        provider_family="local",
        upstream_id="local/model",
        architecture="x",
        parameter_class="small",
        quantization="q4",
        tokenizer_sha256="b" * 64,
        context_tokens=1,
        license_id="MIT",
        source_manifest_artifact_id="sha256:" + "c" * 64,
        local_path=tmp_path / "model",
        capabilities=frozenset({ModelCapability.TEXT_GENERATION}),
        approved_tasks=frozenset(),
    )
    with pytest.raises(ValidationError):
        ModelArtifact(**(values | {"context_tokens": "1"}))
    with pytest.raises(ValidationError):
        ModelArtifact(**values, unknown=True)


def test_lifecycle_closure_includes_terminal_rejected() -> None:
    assert ModelLifecycle.REJECTED.value == "rejected"


def _artifact_values(tmp_path: Path) -> dict[str, object]:
    return {
        "artifact_id": uuid4(),
        "sha256": "a" * 64,
        "provider_family": "local_mlx",
        "upstream_id": "rsitech/atlas-model.v1",
        "architecture": "transformer_v2",
        "parameter_class": "small_7b",
        "quantization": "q4_k_m",
        "tokenizer_sha256": "b" * 64,
        "context_tokens": 131_072,
        "license_id": "Apache-2.0",
        "source_manifest_artifact_id": "sha256:" + "c" * 64,
        "local_path": (tmp_path / "model.gguf").resolve(),
        "capabilities": frozenset({ModelCapability.TEXT_GENERATION}),
        "capability_results": frozenset({"schema_valid_v1"}),
        "approved_tasks": frozenset({"research_planner"}),
        "lifecycle": ModelLifecycle.IMPORTED,
    }


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("artifact_id", UUID(int=0)),
        ("sha256", "A" * 64),
        ("sha256", "a" * 63),
        ("provider_family", "local model"),
        ("provider_family", "l" + chr(0x043E) + "cal"),
        ("architecture", "transformer\nprivate"),
        ("parameter_class", "/private/model"),
        ("quantization", "https://example.invalid"),
        ("upstream_id", "org/../private"),
        ("upstream_id", "https://example.invalid/model"),
        ("upstream_id", "org//model"),
        ("tokenizer_sha256", "b" * 65),
        ("context_tokens", 0),
        ("context_tokens", 10_000_001),
        ("license_id", "private license text"),
        ("source_manifest_artifact_id", "sha256:" + "C" * 64),
        ("local_path", Path("relative/model.gguf")),
        ("local_path", Path("/tmp/../tmp/model.gguf")),
        ("capability_results", frozenset({"free form benchmark text"})),
        ("capability_results", frozenset({"result\nprivate"})),
        ("approved_tasks", frozenset({"/private/task"})),
        ("approved_tasks", frozenset({"https://example.invalid"})),
        ("lifecycle", "imported"),
    ],
)
def test_model_artifact_rejects_unbounded_or_coerced_boundary_values(
    tmp_path: Path,
    field: str,
    value: object,
) -> None:
    values = _artifact_values(tmp_path)
    values[field] = value

    with pytest.raises(ValidationError):
        ModelArtifact(**values)


@pytest.mark.parametrize("field", ["capability_results", "approved_tasks"])
def test_model_artifact_bounds_compact_identifier_collections(
    tmp_path: Path,
    field: str,
) -> None:
    values = _artifact_values(tmp_path)
    values[field] = frozenset(f"identifier_{index}" for index in range(65))

    with pytest.raises(ValidationError):
        ModelArtifact(**values)


def test_model_artifact_is_frozen_with_immutable_collections(tmp_path: Path) -> None:
    artifact = ModelArtifact(**_artifact_values(tmp_path))

    assert isinstance(artifact.capabilities, frozenset)
    assert isinstance(artifact.capability_results, frozenset)
    assert isinstance(artifact.approved_tasks, frozenset)
    with pytest.raises(ValidationError, match="frozen_instance"):
        artifact.lifecycle = ModelLifecycle.PRODUCTION
