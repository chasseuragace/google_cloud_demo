import os
import socket
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=Path(__file__).resolve().parents[1] / ".env", extra="ignore", case_sensitive=False)

    database_master_url: str = ""
    database_replica_url: str = ""
    redis_url: str | None = None
    worker_id: str = socket.gethostname()
    cache_ttl_seconds: int = 30

    @property
    def master_url(self) -> str:
        return self.database_master_url

    @property
    def replica_url(self) -> str:
        return self.database_replica_url


settings = Settings()
