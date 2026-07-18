from rsi_atlas_models.provider import UnavailableModelProvider


def test_unavailable_provider_is_constructible() -> None:
    assert UnavailableModelProvider().health.state.value == "unavailable"
