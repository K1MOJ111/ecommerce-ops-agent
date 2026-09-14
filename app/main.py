from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.routes.health import router as health_router
from app.api.routes.agent import router as agent_router
from app.agent.llm import OpenAICompatibleModel
from app.core.config import Settings, get_settings
from app.db.session import create_db_engine, create_session_factory


def create_app(settings: Settings | None = None) -> FastAPI:
    @asynccontextmanager
    async def lifespan(application: FastAPI) -> AsyncIterator[None]:
        config = settings or get_settings()
        engine = create_db_engine(config.database_url.get_secret_value())
        application.state.session_factory = create_session_factory(engine)
        application.state.settings = config
        application.state.agent_model = OpenAICompatibleModel(config)
        try:
            yield
        finally:
            await engine.dispose()

    application = FastAPI(title="Ecommerce Ops Agent", lifespan=lifespan)
    application.include_router(health_router)
    application.include_router(agent_router)
    return application


app = create_app()
