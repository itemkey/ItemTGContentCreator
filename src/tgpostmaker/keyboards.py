from __future__ import annotations

from aiogram.types import (
    ChatAdministratorRights,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    KeyboardButtonRequestChat,
    ReplyKeyboardMarkup,
)

from tgpostmaker.buttons import ButtonRows, flatten_buttons
from tgpostmaker.db import ChannelRecord


CHANNEL_REQUEST_ID = 1001


def channel_request_keyboard() -> ReplyKeyboardMarkup:
    rights = channel_posting_rights()
    return ReplyKeyboardMarkup(
        keyboard=[
            [
                KeyboardButton(
                    text="Выбрать канал",
                    request_chat=KeyboardButtonRequestChat(
                        request_id=CHANNEL_REQUEST_ID,
                        chat_is_channel=True,
                        user_administrator_rights=rights,
                        bot_administrator_rights=rights,
                        request_title=True,
                        request_username=True,
                    ),
                )
            ]
        ],
        resize_keyboard=True,
        one_time_keyboard=True,
        input_field_placeholder="Выберите канал для публикации",
    )


def channel_posting_rights() -> ChatAdministratorRights:
    return ChatAdministratorRights(
        is_anonymous=False,
        can_manage_chat=False,
        can_delete_messages=False,
        can_manage_video_chats=False,
        can_restrict_members=False,
        can_promote_members=False,
        can_change_info=False,
        can_invite_users=False,
        can_post_stories=False,
        can_edit_stories=False,
        can_delete_stories=False,
        can_post_messages=True,
        can_edit_messages=False,
        can_pin_messages=False,
        can_manage_topics=False,
    )


def channels_keyboard(
    channels: list[ChannelRecord],
    selected_channel_id: int | None,
) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    for channel in channels:
        prefix = "✓ " if channel.chat_id == selected_channel_id else ""
        rows.append(
            [
                InlineKeyboardButton(
                    text=f"{prefix}{channel.title}",
                    callback_data=f"channel:select:{channel.chat_id}",
                )
            ]
        )
    rows.append(
        [
            InlineKeyboardButton(
                text="➕ Добавить канал",
                callback_data="channel:add",
            )
        ]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def main_menu_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Автопост", callback_data="autopost:start")],
            [InlineKeyboardButton(text="Сменить канал", callback_data="channel:list")],
            [InlineKeyboardButton(text="➕ Добавить канал", callback_data="channel:add")],
        ]
    )


def draft_controls_keyboard(draft_id: int, has_buttons: bool) -> InlineKeyboardMarkup:
    rows = [[InlineKeyboardButton(text="Добавить кнопку", callback_data=f"draft:add:{draft_id}")]]
    if has_buttons:
        rows.append(
            [
                InlineKeyboardButton(
                    text="Редактировать кнопки",
                    callback_data=f"draft:edit:{draft_id}",
                )
            ]
        )
        rows.append(
            [
                InlineKeyboardButton(
                    text="Удалить кнопку",
                    callback_data=f"draft:delete:{draft_id}",
                )
            ]
        )
    rows.append(
        [
            InlineKeyboardButton(
                text="Запланировать",
                callback_data=f"draft:schedule:{draft_id}",
            ),
            InlineKeyboardButton(
                text="Опубликовать",
                callback_data=f"draft:publish:{draft_id}",
            ),
        ]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def delete_buttons_keyboard(draft_id: int, rows: ButtonRows) -> InlineKeyboardMarkup:
    keyboard: list[list[InlineKeyboardButton]] = []
    for flat_index, (_, _, button) in enumerate(flatten_buttons(rows), start=1):
        keyboard.append(
            [
                InlineKeyboardButton(
                    text=f"{flat_index}. {button.text}",
                    callback_data=f"button:delete:{draft_id}:{flat_index - 1}",
                )
            ]
        )
    keyboard.append(
        [
            InlineKeyboardButton(
                text="Готово",
                callback_data=f"draft:controls:{draft_id}",
            )
        ]
    )
    return InlineKeyboardMarkup(inline_keyboard=keyboard)

