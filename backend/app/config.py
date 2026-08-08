from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=None, extra="ignore")

    app_env: str = "development"
    app_base_url: str = "http://localhost:8000"
    data_dir: Path = Path("data")
    database_url: str = "sqlite:///./data/db/sofa_prompt_workbench.db"
    redis_url: str = "redis://localhost:6379/0"
    local_inline_worker: bool = False
    session_secret: str = Field(default="development-only-change-me", min_length=16)
    session_ttl_seconds: int = 12 * 60 * 60
    secure_cookies: bool = False
    cookie_domain: str | None = None
    login_rate_limit: int = 10
    max_upload_bytes: int = 20 * 1024 * 1024
    max_image_pixels: int = 40_000_000
    oneimg_base_url: str | None = None
    oneimg_api_token: str | None = None
    oneimg_timeout_seconds: float = 120
    ai_base_url: str | None = None
    ai_api_key: str | None = None
    ai_model: str | None = None
    ai_chat_completions_path: str = "/chat/completions"
    ai_timeout_seconds: float = 240
    skill_root: Path | None = None

    def validate_production(self) -> None:
        if self.app_env != "production":
            return
        if self.session_secret == "development-only-change-me":
            raise ValueError("生产环境必须设置随机 SESSION_SECRET")
        if not self.secure_cookies:
            raise ValueError("生产环境必须启用 SECURE_COOKIES")
        if not self.oneimg_base_url or not self.oneimg_api_token:
            raise ValueError("生产环境必须配置 OneImg")
        if not self.ai_base_url or not self.ai_api_key or not self.ai_model:
            raise ValueError("生产环境必须配置视觉模型")
        if self.database_url == "sqlite:///./data/db/sofa_prompt_workbench.db":
            raise ValueError("生产环境必须显式配置 DATABASE_URL")
        if self.redis_url == "redis://localhost:6379/0":
            raise ValueError("生产环境必须显式配置 REDIS_URL")


@lru_cache
def get_settings() -> Settings:
    return Settings()
