import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent


@dataclass(frozen=True)
class Settings:
    telegram_token: str = field(repr=False)
    openai_api_key: str = field(repr=False)
    allowed_user_ids: frozenset[int]
    model: str
    database_path: Path
    daily_request_limit: int
    provider: str = "ollama"
    ollama_url: str = "http://127.0.0.1:11434"


def load_settings() -> Settings:
    load_dotenv(ROOT / ".env")
    try:
        allowed = frozenset(
            int(value.strip())
            for value in os.getenv("ALLOWED_USER_IDS", "").split(",")
            if value.strip()
        )
        limit = int(os.getenv("DAILY_AI_REQUEST_LIMIT", "40"))
    except ValueError as exc:
        raise ValueError("В ALLOWED_USER_IDS и DAILY_AI_REQUEST_LIMIT нужны числа.") from exc
    if len(allowed) > 2 or any(value <= 0 for value in allowed):
        raise ValueError("В ALLOWED_USER_IDS укажи один или два положительных Telegram ID.")
    if not 1 <= limit <= 500:
        raise ValueError("DAILY_AI_REQUEST_LIMIT должен быть от 1 до 500.")
    provider = os.getenv("AI_PROVIDER", "ollama").strip().lower()
    if provider not in {"ollama", "openai"}:
        raise ValueError("AI_PROVIDER должен быть ollama или openai.")
    default_model = "qwen3:4b-instruct-2507-q4_K_M" if provider == "ollama" else "gpt-4.1-mini"
    model_name = "OLLAMA_MODEL" if provider == "ollama" else "OPENAI_MODEL"
    model = os.getenv(model_name, default_model).strip()
    if not model:
        raise ValueError(f"Укажи {model_name} в .env.")
    ollama_url = os.getenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434").strip().rstrip("/")
    if not ollama_url:
        raise ValueError("OLLAMA_BASE_URL не должен быть пустым.")
    database = Path(os.getenv("DATABASE_PATH", "data/analystmock.sqlite3"))
    if not database.is_absolute():
        database = ROOT / database
    return Settings(
        telegram_token=os.getenv("TELEGRAM_BOT_TOKEN", "").strip(),
        openai_api_key=os.getenv("OPENAI_API_KEY", "").strip(),
        allowed_user_ids=allowed,
        model=model,
        database_path=database,
        daily_request_limit=limit,
        provider=provider,
        ollama_url=ollama_url,
    )
