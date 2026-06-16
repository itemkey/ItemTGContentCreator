from __future__ import annotations

import re
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo


class ScheduleParseError(ValueError):
    pass


RELATIVE_RE = re.compile(
    r"^через\s+(\d+)\s*(минут(?:у|ы)?|мин|м|час(?:а|ов)?|ч|дн(?:я|ей)?)$",
    re.IGNORECASE,
)
DAY_RE = re.compile(r"^(сегодня|завтра)\s+(\d{1,2}):(\d{2})$", re.IGNORECASE)
DATE_RE = re.compile(
    r"^(\d{1,2})\.(\d{1,2})(?:\.(\d{2}|\d{4}))?\s+(\d{1,2}):(\d{2})$"
)
ISO_RE = re.compile(r"^(\d{4})-(\d{1,2})-(\d{1,2})\s+(\d{1,2}):(\d{2})$")


def parse_schedule_input(
    raw_text: str,
    *,
    now: datetime | None = None,
    timezone_name: str = "Europe/Minsk",
) -> datetime:
    tz = ZoneInfo(timezone_name)
    current = _normalize_now(now, tz)
    text = " ".join(raw_text.strip().lower().split())
    if not text:
        raise ScheduleParseError("Время публикации не указано.")

    scheduled = _parse_relative(text, current)
    if scheduled is None:
        scheduled = _parse_day_word(text, current, tz)
    if scheduled is None:
        scheduled = _parse_dot_date(text, current, tz)
    if scheduled is None:
        scheduled = _parse_iso_date(text, tz)
    if scheduled is None:
        raise ScheduleParseError(
            "Не понял время. Примеры: сегодня 18:00, завтра 09:30, через 2 часа, 25.06 14:00."
        )
    if scheduled <= current:
        raise ScheduleParseError("Время публикации уже прошло.")
    return scheduled


def format_schedule(dt: datetime, timezone_name: str = "Europe/Minsk") -> str:
    local_dt = dt.astimezone(ZoneInfo(timezone_name))
    return local_dt.strftime("%d.%m.%Y %H:%M")


def to_utc_iso(dt: datetime) -> str:
    return dt.astimezone(ZoneInfo("UTC")).isoformat()


def from_utc_iso(raw: str | None) -> datetime | None:
    if not raw:
        return None
    return datetime.fromisoformat(raw).astimezone(ZoneInfo("UTC"))


def _normalize_now(now: datetime | None, tz: ZoneInfo) -> datetime:
    if now is None:
        return datetime.now(tz)
    if now.tzinfo is None:
        return now.replace(tzinfo=tz)
    return now.astimezone(tz)


def _parse_relative(text: str, current: datetime) -> datetime | None:
    match = RELATIVE_RE.match(text)
    if not match:
        return None
    amount = int(match.group(1))
    unit = match.group(2)
    if amount <= 0:
        raise ScheduleParseError("Укажите число больше нуля.")
    if unit.startswith(("мин", "м")):
        return current + timedelta(minutes=amount)
    if unit.startswith(("час", "ч")):
        return current + timedelta(hours=amount)
    return current + timedelta(days=amount)


def _parse_day_word(text: str, current: datetime, tz: ZoneInfo) -> datetime | None:
    match = DAY_RE.match(text)
    if not match:
        return None
    day_word, raw_hour, raw_minute = match.groups()
    hour, minute = _parse_time(raw_hour, raw_minute)
    day_offset = 1 if day_word == "завтра" else 0
    target_date = current.date() + timedelta(days=day_offset)
    return datetime(
        target_date.year,
        target_date.month,
        target_date.day,
        hour,
        minute,
        tzinfo=tz,
    )


def _parse_dot_date(text: str, current: datetime, tz: ZoneInfo) -> datetime | None:
    match = DATE_RE.match(text)
    if not match:
        return None
    raw_day, raw_month, raw_year, raw_hour, raw_minute = match.groups()
    day = int(raw_day)
    month = int(raw_month)
    hour, minute = _parse_time(raw_hour, raw_minute)
    if raw_year:
        year = int(raw_year)
        if year < 100:
            year += 2000
        return _safe_datetime(year, month, day, hour, minute, tz)

    scheduled = _safe_datetime(current.year, month, day, hour, minute, tz)
    if scheduled <= current:
        scheduled = _safe_datetime(current.year + 1, month, day, hour, minute, tz)
    return scheduled


def _parse_iso_date(text: str, tz: ZoneInfo) -> datetime | None:
    match = ISO_RE.match(text)
    if not match:
        return None
    raw_year, raw_month, raw_day, raw_hour, raw_minute = match.groups()
    hour, minute = _parse_time(raw_hour, raw_minute)
    return _safe_datetime(
        int(raw_year),
        int(raw_month),
        int(raw_day),
        hour,
        minute,
        tz,
    )


def _parse_time(raw_hour: str, raw_minute: str) -> tuple[int, int]:
    hour = int(raw_hour)
    minute = int(raw_minute)
    if hour > 23 or minute > 59:
        raise ScheduleParseError("Некорректное время.")
    return hour, minute


def _safe_datetime(
    year: int,
    month: int,
    day: int,
    hour: int,
    minute: int,
    tz: ZoneInfo,
) -> datetime:
    try:
        return datetime(year, month, day, hour, minute, tzinfo=tz)
    except ValueError as exc:
        raise ScheduleParseError("Некорректная дата.") from exc

