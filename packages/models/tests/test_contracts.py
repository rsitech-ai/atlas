from pathlib import Path
from uuid import uuid4

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
        source_manifest_id="sha256:" + "c" * 64,
        local_path=tmp_path / "model",
        capabilities=frozenset({ModelCapability.GENERATE}),
        approved_tasks=frozenset(),
    )
    with pytest.raises(ValidationError):
        ModelArtifact(**(values | {"context_tokens": "1"}))
    with pytest.raises(ValidationError):
        ModelArtifact(**values, unknown=True)


def test_lifecycle_closure_includes_terminal_rejected() -> None:
    assert ModelLifecycle.REJECTED.value == "rejected"
