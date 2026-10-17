from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

BOT_DIR = Path(__file__).resolve().parent
load_dotenv(BOT_DIR / ".env")


def _ids(value: str) -> frozenset[int]:
    result: set[int] = set()
    for part in value.split(","):
        part = part.strip()
        if part:
            result.add(int(part))
    return frozenset(result)


def _bool(value: str | None, default: bool = False) -> bool:
    if not value:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    bot_token: str
    admin_user_ids: frozenset[int]
    participant_user_ids: frozenset[int]
    database_path: Path
    ai_api_key: str
    ai_base_url: str
    ai_model: str
    ai_enabled: bool
    max_context_messages: int
    conflict_threshold: float
    auto_check_every: int
    auto_offer_cooldown_seconds: int
    ai_timeout_seconds: int
    ai_max_tokens: int

    @property
    def ai_configured(self) -> bool:
        return bool(self.ai_api_key)


def load_settings() -> Settings:
    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    if not token:
        raise ValueError("TELEGRAM_BOT_TOKEN is missing. Copy .env.example to .env and add your bot token.")

    admins = _ids(os.getenv("ADMIN_USER_IDS", ""))
    if not admins:
        raise ValueError("ADMIN_USER_IDS must contain at least one Telegram user ID.")

    participants = _ids(os.getenv("MEDIATION_PARTICIPANT_IDS", ""))
    if participants and len(participants) != 2:
        raise ValueError("MEDIATION_PARTICIPANT_IDS must be empty or contain exactly two user IDs.")

    threshold = float(os.getenv("CONFLICT_DETECTION_THRESHOLD", "0.82"))
    if not 0 <= threshold <= 1:
        raise ValueError("CONFLICT_DETECTION_THRESHOLD must be between 0 and 1.")

    database_path = Path(os.getenv("DATABASE_PATH", "data/bot.sqlite3"))
    if not database_path.is_absolute():
        database_path = BOT_DIR / database_path

    return Settings(
        bot_token=token,
        admin_user_ids=admins,
        participant_user_ids=participants,
        database_path=database_path,
        ai_api_key=os.getenv("AI_API_KEY", "").strip(),
        ai_base_url=os.getenv("AI_BASE_URL", "https://api.openai.com/v1").strip().rstrip("/"),
        ai_model=os.getenv("AI_MODEL", "gpt-4o-mini").strip(),
        ai_enabled=_bool(os.getenv("AI_ENABLED", "true"), default=True),
        max_context_messages=max(4, min(50, int(os.getenv("MAX_CONTEXT_MESSAGES", "20")))),
        conflict_threshold=threshold,
        auto_check_every=max(1, int(os.getenv("AUTO_CHECK_EVERY", "3"))),
        auto_offer_cooldown_seconds=max(60, int(os.getenv("AUTO_OFFER_COOLDOWN_SECONDS", "300"))),
        ai_timeout_seconds=max(5, int(os.getenv("AI_TIMEOUT_SECONDS", "25"))),
        ai_max_tokens=max(100, min(1500, int(os.getenv("AI_MAX_TOKENS", "500")))),
    )
