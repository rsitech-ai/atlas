from dataclasses import dataclass
from typing import Protocol

from rsi_atlas_contracts.models import ModelCapability, ProviderHealthState


class ProviderUnavailableError(RuntimeError):
    code = "provider_unavailable"


@dataclass(frozen=True)
class ProviderHealth:
    state: ProviderHealthState


class ModelProvider(Protocol):
    @property
    def capabilities(self) -> frozenset[ModelCapability]: ...
    @property
    def health(self) -> ProviderHealth: ...
    def generate(self, request: object) -> object: ...
    def stream(self, request: object) -> object: ...
    def unload(self) -> None: ...


class UnavailableModelProvider:
    @property
    def capabilities(self) -> frozenset[ModelCapability]:
        return frozenset()

    @property
    def health(self) -> ProviderHealth:
        return ProviderHealth(ProviderHealthState.UNAVAILABLE)

    def generate(self, request: object) -> object:
        raise ProviderUnavailableError(self.code)

    def stream(self, request: object) -> object:
        raise ProviderUnavailableError(self.code)

    def unload(self) -> None:
        return None

    code = "provider_unavailable"
