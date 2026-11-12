from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    DATABASE_URL: str = Field(
        default="postgresql+psycopg2://postgres:postgres@localhost:5432/ai_copilot"
    )
    DB_ECHO: bool = False

    # LLM providers for the planner adapter. Tried in this order; a provider
    # with an empty key is skipped. See app/integrations/llm/gateway.py.
    GEMINI_API_KEY: str = ""
    GEMINI_MODEL: str = "gemini-3.5-flash"
    GROQ_API_KEY: str = ""
    GROQ_MODEL: str = "openai/gpt-oss-120b"
    OPENROUTER_API_KEY: str = ""
    OPENROUTER_MODEL: str = "openrouter/free"
    LLM_TIMEOUT_S: int = 30
    LLM_MAX_RETRIES: int = Field(default=3, ge=1)
    LLM_SCHEMA_REPAIR_ATTEMPTS: int = Field(default=1, ge=0)
    # Planner-side policy (the backend validates again; this is the first gate).
    PLANNER_MIN_CONFIDENCE: float = Field(default=0.5, ge=0.0, le=1.0)
    PLANNER_ALLOW_INLINE_CODE: bool = False

    # Minimal sandbox check (prototype; the real profile is the backend owner's).
    SANDBOX_IMAGE: str = "python:3.12-alpine"
    SANDBOX_TIMEOUT_S: int = Field(default=30, ge=1, le=120)


settings = Settings()
