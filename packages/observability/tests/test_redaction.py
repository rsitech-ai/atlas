from uuid import UUID

import pytest
from rsi_atlas_observability.redaction import SensitiveTraceAttributeError, validate_attribute


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("document.text", "private body"),
        ("atlas.command.name", "this is arbitrary private prose"),
        ("atlas.command.name", "private\nmessage"),
        ("atlas.count", float("nan")),
        ("atlas.count", float("inf")),
        ("atlas.artifact.id", "sha256:" + "A" * 64),
        ("atlas.unknown", "safe-looking"),
        ("atlas.workspace.id", "not-a-uuid"),
        ("atlas.command.name", "\uff24\uff4f\uff43\uff54\uff4f\uff52"),
        ("atlas.command.name", "/private/path"),
        ("atlas.command.name", "https://example.invalid"),
    ],
)
def test_unsafe_or_arbitrary_values_are_rejected_before_collection(
    name: str,
    value: object,
) -> None:
    with pytest.raises(SensitiveTraceAttributeError):
        validate_attribute(name, value)


def test_exact_safe_attributes_are_typed_and_bounded() -> None:
    assert validate_attribute("atlas.command.name", "Doctor") == "Doctor"
    assert validate_attribute("atlas.count", 2) == 2
    assert validate_attribute("atlas.score", 0.25) == 0.25
    workspace = UUID("22222222-2222-4222-8222-222222222222")
    assert validate_attribute("atlas.workspace.id", workspace) == str(workspace)
