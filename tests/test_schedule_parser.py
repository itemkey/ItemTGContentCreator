from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from tgpostmaker.schedule_parser import ScheduleParseError, parse_schedule_input


TZ = "Europe/Minsk"
NOW = datetime(2026, 6, 16, 12, 0, tzinfo=ZoneInfo(TZ))


def test_parse_today() -> None:
    scheduled = parse_schedule_input("сегодня 18:00", now=NOW, timezone_name=TZ)

    assert scheduled == datetime(2026, 6, 16, 18, 0, tzinfo=ZoneInfo(TZ))


def test_parse_tomorrow() -> None:
    scheduled = parse_schedule_input("завтра 09:30", now=NOW, timezone_name=TZ)

    assert scheduled == datetime(2026, 6, 17, 9, 30, tzinfo=ZoneInfo(TZ))


def test_parse_relative_hours() -> None:
    scheduled = parse_schedule_input("через 2 часа", now=NOW, timezone_name=TZ)

    assert scheduled == datetime(2026, 6, 16, 14, 0, tzinfo=ZoneInfo(TZ))


def test_parse_dot_date_without_year_uses_next_occurrence() -> None:
    scheduled = parse_schedule_input("25.06 14:00", now=NOW, timezone_name=TZ)

    assert scheduled == datetime(2026, 6, 25, 14, 0, tzinfo=ZoneInfo(TZ))


def test_parse_dot_date_without_year_rolls_to_next_year_when_needed() -> None:
    scheduled = parse_schedule_input("15.06 14:00", now=NOW, timezone_name=TZ)

    assert scheduled == datetime(2027, 6, 15, 14, 0, tzinfo=ZoneInfo(TZ))


def test_rejects_past_explicit_day_word() -> None:
    with pytest.raises(ScheduleParseError):
        parse_schedule_input("сегодня 11:59", now=NOW, timezone_name=TZ)


def test_rejects_unknown_text() -> None:
    with pytest.raises(ScheduleParseError):
        parse_schedule_input("после обеда", now=NOW, timezone_name=TZ)

