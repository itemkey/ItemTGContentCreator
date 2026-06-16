import pytest

from tgpostmaker.buttons import (
    ButtonParseError,
    deserialize_buttons,
    flatten_buttons,
    normalize_url,
    parse_buttons,
    remove_button_at,
    serialize_buttons,
)


def test_normalize_tme_link() -> None:
    assert normalize_url("t.me/example") == "https://t.me/example"


def test_parse_rows_styles_and_columns() -> None:
    rows = parse_buttons(
        "!r Купить - t.me/shop | !g Подробнее - https://example.com\n"
        "!b Написать - tg://resolve?domain=test"
    )

    assert [[button.text for button in row] for row in rows] == [
        ["Купить", "Подробнее"],
        ["Написать"],
    ]
    assert [[button.style for button in row] for row in rows] == [
        ["danger", "success"],
        ["primary"],
    ]
    assert rows[0][0].url == "https://t.me/shop"


def test_parse_rejects_bad_format() -> None:
    with pytest.raises(ButtonParseError):
        parse_buttons("Купить t.me/shop")


def test_parse_rejects_bad_url() -> None:
    with pytest.raises(ButtonParseError):
        parse_buttons("Купить - ftp://example.com")


def test_serialize_roundtrip_and_remove_flat_index() -> None:
    rows = parse_buttons("A - t.me/a | B - t.me/b\nC - t.me/c")
    restored = deserialize_buttons(serialize_buttons(rows))

    assert flatten_buttons(restored)[1][2].text == "B"
    trimmed = remove_button_at(restored, 1)
    assert [[button.text for button in row] for row in trimmed] == [["A"], ["C"]]

