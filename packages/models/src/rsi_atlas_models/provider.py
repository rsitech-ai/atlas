"""Runtime-independent model provider boundary for Phase 1."""

from __future__ import annotations

import re
from collections.abc import Iterator
from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol, runtime_checkable
from uuid import UUID

from rsi_atlas_contracts.models import ModelCapability, ProviderHealthState


class ProviderErrorCode(StrEnum):
    INVALID_REQUEST = "invalid_model_request"
    UNAVAILABLE = "provider_unavailable"


class ProviderUnavailableError(RuntimeError):
    def __init__(self) -> None:
        self.code = ProviderErrorCode.UNAVAILABLE
        super().__init__(self.code.value)


class InvalidModelRequestError(RuntimeError):
    def __init__(self) -> None:
        self.code = ProviderErrorCode.INVALID_REQUEST
        super().__init__(self.code.value)


_TASK_ID = re.compile(r"^[a-z][a-z0-9_]{0,63}$")


@dataclass(frozen=True, slots=True)
class ModelRequest:
    request_id: UUID
    task_id: str

    def __post_init__(self) -> None:
        if type(self.request_id) is not UUID or self.request_id.int == 0:
            raise ValueError("model request identifier must be a UUID")
        if type(self.task_id) is not str or _TASK_ID.fullmatch(self.task_id) is None:
            raise ValueError("model task identifier is invalid")


@dataclass(frozen=True, slots=True)
class ModelResponse:
    request_id: UUID
    provider_state: ProviderHealthState

    def __post_init__(self) -> None:
        if type(self.request_id) is not UUID or self.request_id.int == 0:
            raise ValueError("model response identifier must be a UUID")
        if type(self.provider_state) is not ProviderHealthState:
            raise ValueError("model response provider state is invalid")


@dataclass(frozen=True, slots=True)
class ProviderHealth:
    state: ProviderHealthState

    def __post_init__(self) -> None:
        if type(self.state) is not ProviderHealthState:
            raise ValueError("provider health state is invalid")


@runtime_checkable
class ModelProvider(Protocol):
    @property
    def capabilities(self) -> frozenset[ModelCapability]: ...

    @property
    def health(self) -> ProviderHealth: ...

    def generate(self, request: ModelRequest) -> ModelResponse: ...

    def stream(self, request: ModelRequest) -> Iterator[ModelResponse]: ...

    def unload(self) -> None: ...


class UnavailableModelProvider:
    """A deterministic provider that performs no I/O and never falls back."""

    @property
    def capabilities(self) -> frozenset[ModelCapability]:
        return frozenset()

    @property
    def health(self) -> ProviderHealth:
        return ProviderHealth(ProviderHealthState.UNAVAILABLE)

    def generate(self, request: ModelRequest) -> ModelResponse:
        if type(request) is not ModelRequest:
            raise InvalidModelRequestError
        raise ProviderUnavailableError

    def stream(self, request: ModelRequest) -> Iterator[ModelResponse]:
        if type(request) is not ModelRequest:
            raise InvalidModelRequestError
        raise ProviderUnavailableError

    def unload(self) -> None:
        return None


__all__ = [
    "InvalidModelRequestError",
    "ModelProvider",
    "ModelRequest",
    "ModelResponse",
    "ProviderErrorCode",
    "ProviderHealth",
    "ProviderUnavailableError",
    "UnavailableModelProvider",
]
