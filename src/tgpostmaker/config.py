from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


@dataclass(frozen=True)
class Settings:
    bot_token: str
    admin_ids: frozenset[int]
    timezone: str
    db_path: str
    scheduler_interval_seconds: float


def _parse_admin_ids(raw: str) -> frozenset[int]:
    ids: set[int] = set()
    for item in raw.split(","):
        value = item.strip()
        if not value:
            continue
        try:
            ids.add(int(value))
        except ValueError as exc:
            raise ValueError(f"ADMIN_IDS contains a non-numeric Telegram ID: {value!r}") from exc
    if not ids:
        raise ValueError("ADMIN_IDS must contain at least one Telegram user ID")
    return frozenset(ids)


def load_settings(env_file: str | Path | None = None) -> Settings:
    load_dotenv(env_file)

    bot_token = os.getenv("BOT_TOKEN", "").strip()
    if not bot_token:
        raise ValueError("BOT_TOKEN is required")

    admin_ids = _parse_admin_ids(os.getenv("ADMIN_IDS", ""))
    timezone = os.getenv("TZ", "Europe/Minsk").strip() or "Europe/Minsk"
    db_path = os.getenv("DB_PATH", "/data/bot.db").strip() or "/data/bot.db"

    try:
        interval = float(os.getenv("SCHEDULER_INTERVAL_SECONDS", "5"))
    except ValueError as exc:
        raise ValueError("SCHEDULER_INTERVAL_SECONDS must be a number") from exc
    if interval <= 0:
        raise ValueError("SCHEDULER_INTERVAL_SECONDS must be greater than zero")

    return Settings(
        bot_token=bot_token,
        admin_ids=admin_ids,
        timezone=timezone,
        db_path=db_path,
        scheduler_interval_seconds=interval,
    )

