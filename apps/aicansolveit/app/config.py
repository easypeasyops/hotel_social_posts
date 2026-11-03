from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    # App
    app_name: str = "aicansolveit"
    debug: bool = False
    log_level: str = "INFO"
    log_json: bool = True  # LOG_JSON=false: plain lines for local reading
    secret_key: str  # used for signing internal tokens (upload links etc.)
    public_base_url: str = "http://localhost:8000"

    # Supabase
    supabase_url: str
    supabase_anon_key: str
    supabase_service_role_key: str  # server-side operations only

    # Claude
    anthropic_api_key: str
    claude_draft_model: str = "claude-haiku-4-5-20251001"  # bulk drafts
    claude_premium_model: str = "claude-sonnet-4-6"  # premium tier

    # DeepL
    deepl_api_key: str

    # Buffer
    buffer_access_token: str

    # Redis (Celery broker)
    redis_url: str = "redis://localhost:6379/0"

    # Internal cron secret — Railway cron hits /internal/* with this header
    cron_secret: str

    # Browser session cookie should only travel over HTTPS outside local development.
    session_cookie_secure: bool = True


@lru_cache
def get_settings() -> Settings:
    return Settings()
