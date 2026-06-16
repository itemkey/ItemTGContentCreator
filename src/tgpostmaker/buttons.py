from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from typing import Any
from urllib.parse import urlparse


COLOR_PREFIXES = {
    "!r": "danger",
    "!g": "success",
    "!b": "primary",
}


BUTTONS_INSTRUCTION = """🔗 Формат одной кнопки:
Название - Ссылка

Кнопки в ряд → укажите «|» между ними
Новая строка → новая строка кнопок под постом

🎨 Цвет кнопки (необязательно):
!r — 🔴 красный
!g — 🟢 зелёный
!b — 🔵 синий

Пример: !r Купить - t.me/

Примеры:
Одна кнопка в посте:
Название 1 - t.me/

Две кнопки в ряд:
Название 1 - t.me/ | Название 2 - t.me/

Пять кнопок в посте:
Название 1 - t.me/
Название 2 - t.me/ | Название 3 - t.me/
Название 4 - t.me/ | Название 5 - t.me/"""


class ButtonParseError(ValueError):
    pass


@dataclass(frozen=True)
class ButtonSpec:
    text: str
    url: str
    style: str | None = None


ButtonRows = list[list[ButtonSpec]]


def normalize_url(raw_url: str) -> str:
    url = raw_url.strip()
    if not url:
        raise ButtonParseError("Ссылка не может быть пустой.")
    if url.startswith("t.me/"):
        url = f"https://{url}"

    parsed = urlparse(url)
    if parsed.scheme in {"http", "https"} and parsed.netloc:
        return url
    if parsed.scheme == "tg" and parsed.netloc:
        return url
    raise ButtonParseError(
        "Ссылка должна начинаться с https://, http://, tg:// или t.me/."
    )


def parse_buttons(text: str) -> ButtonRows:
    rows: ButtonRows = []
    for line_number, line in enumerate(text.splitlines(), start=1):
        stripped_line = line.strip()
        if not stripped_line:
            continue
        row: list[ButtonSpec] = []
        for raw_part in stripped_line.split("|"):
            row.append(_parse_button_part(raw_part, line_number))
        rows.append(row)

    if not rows:
        raise ButtonParseError("Не нашёл ни одной кнопки.")
    return rows


def _parse_button_part(raw_part: str, line_number: int) -> ButtonSpec:
    part = raw_part.strip()
    if not part:
        raise ButtonParseError(f"Пустая кнопка в строке {line_number}.")

    style = None
    for prefix, mapped_style in COLOR_PREFIXES.items():
        if part.startswith(prefix):
            style = mapped_style
            part = part[len(prefix) :].strip()
            break

    if "-" not in part:
        raise ButtonParseError(
            f"Строка {line_number}: используйте формат «Название - Ссылка»."
        )

    title, _, raw_url = part.partition("-")
    title = title.strip()
    if not title:
        raise ButtonParseError(f"Строка {line_number}: название кнопки пустое.")
    if len(title) > 64:
        raise ButtonParseError(f"Строка {line_number}: название длиннее 64 символов.")

    return ButtonSpec(text=title, url=normalize_url(raw_url), style=style)


def serialize_buttons(rows: ButtonRows) -> str:
    return json.dumps(
        [[asdict(button) for button in row] for row in rows],
        ensure_ascii=False,
        separators=(",", ":"),
    )


def deserialize_buttons(raw_json: str | None) -> ButtonRows:
    if not raw_json:
        return []
    raw_rows = json.loads(raw_json)
    return [
        [
            ButtonSpec(
                text=str(button["text"]),
                url=str(button["url"]),
                style=button.get("style"),
            )
            for button in row
        ]
        for row in raw_rows
    ]


def flatten_buttons(rows: ButtonRows) -> list[tuple[int, int, ButtonSpec]]:
    return [
        (row_index, button_index, button)
        for row_index, row in enumerate(rows)
        for button_index, button in enumerate(row)
    ]


def remove_button_at(rows: ButtonRows, flat_index: int) -> ButtonRows:
    mutable_rows = [list(row) for row in rows]
    flattened = flatten_buttons(mutable_rows)
    if flat_index < 0 or flat_index >= len(flattened):
        raise IndexError("Button index is out of range")

    row_index, button_index, _ = flattened[flat_index]
    del mutable_rows[row_index][button_index]
    return [row for row in mutable_rows if row]


def to_inline_keyboard_data(rows: ButtonRows) -> dict[str, Any] | None:
    if not rows:
        return None
    keyboard: list[list[dict[str, str]]] = []
    for row in rows:
        keyboard_row: list[dict[str, str]] = []
        for button in row:
            payload = {"text": button.text, "url": button.url}
            if button.style:
                payload["style"] = button.style
            keyboard_row.append(payload)
        keyboard.append(keyboard_row)
    return {"inline_keyboard": keyboard}


def to_inline_keyboard_markup(rows: ButtonRows) -> Any | None:
    data = to_inline_keyboard_data(rows)
    if data is None:
        return None

    from aiogram.types import InlineKeyboardMarkup

    return InlineKeyboardMarkup.model_validate(data)

