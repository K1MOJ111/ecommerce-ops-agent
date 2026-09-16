from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes.health import router as health_router
from app.api.routes.agent import router as agent_router
from app.agent.llm import OpenAICompatibleModel
from app.agent.development import DevelopmentModel
from app.rag.embedding import FakeEmbeddingProvider
from app.core.observability import configure_logging
from app.core.config import Settings, get_settings
from app.db.session import create_db_engine, create_session_factory


def create_app(settings: Settings | None = None) -> FastAPI:
    @asynccontextmanager
    async def lifespan(application: FastAPI) -> AsyncIterator[None]:
        configure_logging()
        config = settings or get_settings()
        engine = create_db_engine(config.database_url.get_secret_value())
        application.state.session_factory = create_session_factory(engine)
        application.state.settings = config
        application.state.agent_model = DevelopmentModel() if config.agent_provider == "fake" else OpenAICompatibleModel(config)
        application.state.embedding = FakeEmbeddingProvider() if config.embedding_provider == "fake" else None
        try:
            yield
        finally:
            await engine.dispose()

    application = FastAPI(title="Ecommerce Ops Agent", lifespan=lifespan)
    # Resolve settings when middleware starts, preserving import without local credentials.
    def cors(app):
        config = settings or get_settings()
        origins = config.cors_origins or ([] if config.app_env == "production" else
                                         ["http://localhost:5173", "http://127.0.0.1:5173"])
        return CORSMiddleware(app, allow_origins=origins, allow_methods=["GET", "POST"],
                              allow_headers=["Content-Type"])

    application.add_middleware(cors)
    application.include_router(health_router)
    application.include_router(agent_router)
    return application


app = create_app()
