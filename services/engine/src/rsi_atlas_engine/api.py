from collections.abc import Callable

from fastapi import FastAPI
from rsi_atlas_contracts import SystemStatus

from rsi_atlas_engine.diagnostics import build_system_status


def create_app(
    status_factory: Callable[[], SystemStatus] = build_system_status,
) -> FastAPI:
    application = FastAPI(
        title="RSI Atlas Engine",
        version="0.1.0",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )

    @application.get("/v1/system/status", response_model=SystemStatus)
    def system_status() -> SystemStatus:
        return status_factory()

    return application


app = create_app()
