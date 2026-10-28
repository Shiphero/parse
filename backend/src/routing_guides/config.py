from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(extra="ignore")
    database_url: SecretStr
    storage_root: Path = Path("/data")
    max_upload_mb: int = Field(default=256, ge=1)
    credentials_mode: Literal['local', 'environment'] = 'local'
    anthropic_api_key: SecretStr = SecretStr("")
    anthropic_model: str = "claude-opus-5-5"
    openai_api_key: SecretStr = SecretStr("")
    openai_model: str = ""
    litellm_api_key: SecretStr = SecretStr("")
    litellm_model: str = ""
    litellm_base_url: str = "https://litellm.tools.shiphero.com/v1"
    jev_api_key: SecretStr = SecretStr("")
    jev_model: str = "jev-1.14.0"


@lru_cache
def get_settings() -> Settings:
    return Settings()
