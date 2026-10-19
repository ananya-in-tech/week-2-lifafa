from functools import lru_cache
from pathlib import Path
from urllib.parse import urlparse

from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parents[1]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=ROOT / ".env", env_file_encoding="utf-8", extra="ignore")

    data_dir: Path = ROOT / "data"
    timezone: str = "Asia/Kolkata"

    ollama_host: str = "http://127.0.0.1:11434"
    ollama_model: str = "gemma4:e2b"
    ollama_timeout_seconds: float = 300.0
    ollama_keep_alive: str = "30m"
    ai_enabled: bool = True
    ai_warmup: bool = True
    allow_remote_ai: bool = False
    voice_enabled: bool = True
    whisper_model: str = "large-v3-turbo"  # "small" is faster but weaker at Hindi numbers

    @property
    def db_path(self) -> Path:
        return self.data_dir / "lifafa.db"

    @property
    def ai_is_local(self) -> bool:
        host = urlparse(self.ollama_host).hostname or ""
        return host in {"127.0.0.1", "localhost", "::1"} and not self.ollama_model.endswith(":cloud")


def check_privacy(s: Settings) -> None:
    """Family names and gift amounts must not leave this machine by accident."""
    if not s.ai_is_local and not s.allow_remote_ai:
        raise RuntimeError("OLLAMA_HOST must be local and the model must not be ':cloud' "
                           "(set ALLOW_REMOTE_AI=true to override deliberately).")


@lru_cache
def get_settings() -> Settings:
    return Settings()
