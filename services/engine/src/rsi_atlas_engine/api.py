from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager, suppress

from fastapi import FastAPI
from rsi_atlas_contracts import SystemStatus

from rsi_atlas_engine.runtime import RuntimeServices


def create_app(
    status_factory: Callable[[], SystemStatus] | None = None,
) -> FastAPI:
    factory = status_factory or RuntimeServices.from_environment().status

    @asynccontextmanager
    async def lifespan(_application: FastAPI) -> AsyncIterator[None]:
        with suppress(Exception):
            factory()
        yield

    application = FastAPI(
        title="RSI Atlas Engine",
        version="0.1.0",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
        lifespan=lifespan,
    )

    @application.get("/v1/system/status", response_model=SystemStatus)
    def system_status() -> SystemStatus:
        return factory()

    return application


app = create_app()
