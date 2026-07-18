import builtins
import copy
import os
import socket
import subprocess
from dataclasses import FrozenInstanceError
from uuid import UUID

import pytest
from rsi_atlas_contracts.models import ProviderHealthState
from rsi_atlas_models.provider import (
    InvalidModelRequestError,
    ModelProvider,
    ModelRequest,
    ModelResponse,
    ProviderErrorCode,
    ProviderUnavailableError,
    UnavailableModelProvider,
)

REQUEST_ID = UUID("11111111-1111-4111-8111-111111111111")


def test_unavailable_provider_conforms_and_fails_with_stable_code() -> None:
    provider = UnavailableModelProvider()
    request = ModelRequest(request_id=REQUEST_ID, task_id="research_planner")

    assert isinstance(provider, ModelProvider)
    assert provider.capabilities == frozenset()
    assert provider.health.state is ProviderHealthState.UNAVAILABLE
    with pytest.raises(ProviderUnavailableError) as generate_error:
        provider.generate(request)
    with pytest.raises(ProviderUnavailableError) as stream_error:
        provider.stream(request)

    assert generate_error.value.code is ProviderErrorCode.UNAVAILABLE
    assert stream_error.value.code is ProviderErrorCode.UNAVAILABLE
    assert str(generate_error.value) == "provider_unavailable"
    provider.unload()
    provider.unload()


def test_provider_boundary_is_immutable_and_strict() -> None:
    request = ModelRequest(request_id=REQUEST_ID, task_id="citation_judge")
    with pytest.raises(FrozenInstanceError):
        request.task_id = "changed"  # type: ignore[misc]
    with pytest.raises(ValueError):
        ModelRequest(request_id=REQUEST_ID, task_id="private task")
    with pytest.raises(ValueError):
        ModelRequest(request_id=str(REQUEST_ID), task_id="citation_judge")  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        ModelRequest(request_id=UUID(int=0), task_id="citation_judge")
    with pytest.raises(ValueError):
        ModelResponse(request_id=UUID(int=0), provider_state=ProviderHealthState.UNAVAILABLE)
    assert copy.copy(request) is not request
    assert copy.copy(request) == request


def test_provider_rejects_invalid_request_objects_before_unavailable_result() -> None:
    provider = UnavailableModelProvider()
    with pytest.raises(InvalidModelRequestError) as generate_error:
        provider.generate(object())  # type: ignore[arg-type]
    with pytest.raises(InvalidModelRequestError) as stream_error:
        provider.stream(object())  # type: ignore[arg-type]
    assert generate_error.value.code is ProviderErrorCode.INVALID_REQUEST
    assert stream_error.value.code is ProviderErrorCode.INVALID_REQUEST


def test_unavailable_provider_performs_no_io_or_environment_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def forbidden(*args: object, **kwargs: object) -> object:
        del args, kwargs
        raise AssertionError("provider attempted I/O")

    monkeypatch.setattr(builtins, "open", forbidden)
    monkeypatch.setattr(os, "getenv", forbidden)
    monkeypatch.setattr(socket, "socket", forbidden)
    monkeypatch.setattr(subprocess, "Popen", forbidden)
    provider = UnavailableModelProvider()
    request = ModelRequest(request_id=REQUEST_ID, task_id="research_planner")

    assert provider.health.state is ProviderHealthState.UNAVAILABLE
    with pytest.raises(ProviderUnavailableError):
        provider.generate(request)
    with pytest.raises(ProviderUnavailableError):
        provider.stream(request)
    provider.unload()
