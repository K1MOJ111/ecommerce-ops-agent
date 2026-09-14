from functools import lru_cache
from typing import Literal

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import make_url
from sqlalchemy.exc import ArgumentError


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore",
        hide_input_in_errors=True,
    )

    app_env: Literal["development", "test", "production"] = "development"
    database_url: SecretStr
    llm_base_url: str | None = None
    llm_api_key: SecretStr | None = None
    llm_model: str | None = None
    llm_timeout_seconds: float = Field(default=30, gt=0, allow_inf_nan=False)
    embedding_base_url: str | None = None
    embedding_api_key: SecretStr | None = None
    embedding_model: str | None = None
    embedding_dim: int | None = Field(default=None, gt=0)
    embedding_timeout_seconds: float = Field(default=30, gt=0, allow_inf_nan=False)
    rag_chunk_size: int = Field(default=800, ge=100, le=10000)
    rag_chunk_overlap: int = Field(default=100, ge=0, le=2000)
    rag_min_similarity: float = Field(default=0.2, ge=0, le=1, allow_inf_nan=False)
    agent_max_tool_calls: int = Field(default=8, gt=0)
    agent_max_graph_steps: int = Field(default=24, gt=0)
    agent_timeout_seconds: float = Field(default=90, gt=0, allow_inf_nan=False)
    rag_top_k: int = Field(default=5, gt=0, le=100)

    @field_validator("embedding_dim", mode="before")
    @classmethod
    def empty_dimension(cls, value: object) -> object:
        return None if value == "" else value

    @field_validator("database_url")
    @classmethod
    def async_postgres_url(cls, value: SecretStr) -> SecretStr:
        try:
            url = make_url(value.get_secret_value())
            valid = url.drivername == "postgresql+asyncpg" and bool(url.database)
        except (ArgumentError, ValueError):
            valid = False
        if not valid:
            raise ValueError("DATABASE_URL must use postgresql+asyncpg and name a database")
        return value


@lru_cache
def get_settings() -> Settings:
    return Settings()
