"""Pure validation for the metadata-only tracing boundary.

This module deliberately validates before collection.  It never attempts to
sanitize arbitrary text after an SDK span has accepted it.
"""

from __future__ import annotations

import math
import re
from collections.abc import Mapping
from typing import Final, TypeAlias
from uuid import UUID


class TracePolicyError(ValueError):
    """Raised when a caller attempts an unsupported tracing operation."""


class SensitiveTraceAttributeError(TracePolicyError):
    """Raised when a metadata attribute cannot safely be collected."""


SUPPORTED_SPAN_NAMES: Final[frozenset[str]] = frozenset(
    {
        "atlas.command",
        "atlas.workflow",
        "atlas.langgraph.node",
        "atlas.agent",
        "atlas.model.generate",
        "atlas.model.embed",
        "atlas.model.rerank",
        "atlas.tool",
        "atlas.retrieve",
        "atlas.parse",
        "atlas.collect",
        "atlas.calculate",
        "atlas.validate",
        "atlas.evaluate",
        "atlas.review",
        "atlas.publish",
        "atlas.codex.turn",
        "atlas.codex.command",
    }
)

CONTEXT_ATTRIBUTE_NAMES: Final[dict[str, str]] = {
    "atlas.tenant.id": "tenant_id",
    "atlas.workspace.id": "workspace_id",
    "atlas.actor.id": "actor_id",
    "atlas.application_trace.id": "trace_id",
}

_COMMAND_NAMES: Final[frozenset[str]] = frozenset(
    {"Collect", "Doctor", "Evaluate", "Parse", "Publish", "Validate"}
)
_ENUM_VALUES: Final[dict[str, frozenset[str]]] = {
    "atlas.command.name": _COMMAND_NAMES,
    "atlas.outcome": frozenset({"failure", "skipped", "success"}),
    "atlas.phase": frozenset({"prepare", "run", "verify"}),
}
_NUMERIC_NAMES: Final[frozenset[str]] = frozenset(
    {"atlas.count", "atlas.duration_ms", "atlas.score", "atlas.size_bytes"}
)
_UUID_NAMES: Final[frozenset[str]] = frozenset({*CONTEXT_ATTRIBUTE_NAMES, "atlas.dataset.id"})
_HASH_NAMES: Final[frozenset[str]] = frozenset({"atlas.artifact.sha256"})
_ARTIFACT_ID_NAMES: Final[frozenset[str]] = frozenset({"atlas.artifact.id"})
_BOOLEAN_NAMES: Final[frozenset[str]] = frozenset({"atlas.cache.hit"})
SAFE_ATTRIBUTE_NAMES: Final[frozenset[str]] = frozenset(
    {
        *_ENUM_VALUES,
        *_NUMERIC_NAMES,
        *_UUID_NAMES,
        *_HASH_NAMES,
        *_ARTIFACT_ID_NAMES,
        *_BOOLEAN_NAMES,
    }
)

_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_ARTIFACT_ID = re.compile(r"^sha256:[0-9a-f]{64}$")
_MAX_NUMBER = 1_000_000_000_000

SafeAttributeValue: TypeAlias = str | int | float | bool


def validate_span_name(name: str) -> str:
    if type(name) is not str or name not in SUPPORTED_SPAN_NAMES:
        raise TracePolicyError("unsupported trace span name")
    return name


def validate_uuid(value: object) -> str:
    candidate = str(value) if isinstance(value, UUID) else value
    if type(candidate) is not str:
        raise SensitiveTraceAttributeError("trace identifier must be a canonical UUID")
    try:
        parsed = UUID(candidate)
    except (TypeError, ValueError) as error:
        raise SensitiveTraceAttributeError("trace identifier must be a canonical UUID") from error
    if str(parsed) != candidate or parsed.version is None:
        raise SensitiveTraceAttributeError("trace identifier must be a canonical UUID")
    return candidate


def validate_attribute(name: object, value: object) -> SafeAttributeValue:
    """Return a typed safe value or fail without retaining caller content."""

    if type(name) is not str or name not in SAFE_ATTRIBUTE_NAMES:
        raise SensitiveTraceAttributeError("trace attribute is not allowlisted")
    if name in _UUID_NAMES:
        return validate_uuid(value)
    if name in _ENUM_VALUES:
        if type(value) is not str or value not in _ENUM_VALUES[name]:
            raise SensitiveTraceAttributeError("trace enum attribute is invalid")
        return value
    if name in _NUMERIC_NAMES:
        if type(value) is not int and type(value) is not float:
            raise SensitiveTraceAttributeError("trace numeric attribute is invalid")
        numeric_value: int | float = value
        numeric = float(numeric_value)
        if not math.isfinite(numeric) or abs(numeric) > _MAX_NUMBER:
            raise SensitiveTraceAttributeError("trace numeric attribute is invalid")
        if name in {"atlas.count", "atlas.size_bytes"} and (
            type(numeric_value) is not int or numeric_value < 0
        ):
            raise SensitiveTraceAttributeError("trace count attribute is invalid")
        return numeric_value
    if name in _BOOLEAN_NAMES:
        if type(value) is not bool:
            raise SensitiveTraceAttributeError("trace boolean attribute is invalid")
        return value
    if name in _HASH_NAMES:
        if type(value) is not str or _SHA256.fullmatch(value) is None:
            raise SensitiveTraceAttributeError("trace digest attribute is invalid")
        return value
    if name in _ARTIFACT_ID_NAMES:
        if type(value) is not str or _ARTIFACT_ID.fullmatch(value) is None:
            raise SensitiveTraceAttributeError("trace artifact identifier is invalid")
        return value
    raise SensitiveTraceAttributeError("trace attribute is not allowlisted")


def validate_attribute_mapping(
    attributes: Mapping[object, object],
) -> dict[str, SafeAttributeValue]:
    if type(attributes) is not dict:
        raise SensitiveTraceAttributeError("trace attributes must be a plain mapping")
    return {str(name): validate_attribute(name, value) for name, value in attributes.items()}
