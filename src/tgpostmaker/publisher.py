from __future__ import annotations

from typing import Any

from aiogram.exceptions import TelegramAPIError

from tgpostmaker.buttons import deserialize_buttons, to_inline_keyboard_markup
from tgpostmaker.db import DraftRecord, Repository


TELEGRAM_CAPTION_LIMIT = 1024
TELEGRAM_TEXT_LIMIT = 4096


class PostingRightsError(RuntimeError):
    pass


class PublishError(RuntimeError):
    pass


def extract_caption_overflow_text(message: Any) -> str | None:
    caption = getattr(message, "caption", None)
    if not caption or len(caption) <= TELEGRAM_CAPTION_LIMIT:
        return None
    return str(caption)


def split_telegram_text(text: str, limit: int = TELEGRAM_TEXT_LIMIT) -> list[str]:
    if limit <= 0:
        raise ValueError("Text chunk limit must be positive")

    chunks: list[str] = []
    remaining = text.strip()
    while len(remaining) > limit:
        split_at = max(
            remaining.rfind("\n", 0, limit + 1),
            remaining.rfind(" ", 0, limit + 1),
        )
        if split_at <= 0:
            split_at = limit

        chunk = remaining[:split_at].rstrip()
        if not chunk:
            chunk = remaining[:limit]
            split_at = limit
        chunks.append(chunk)
        remaining = remaining[split_at:].lstrip()

    if remaining:
        chunks.append(remaining)
    return chunks


async def ensure_bot_can_post(bot: Any, channel_id: int) -> None:
    try:
        me = await bot.get_me()
        member = await bot.get_chat_member(channel_id, me.id)
    except TelegramAPIError as exc:
        raise PostingRightsError(
            "Не могу проверить права в канале. Убедитесь, что бот добавлен администратором."
        ) from exc

    raw_status = getattr(member, "status", "")
    status = getattr(raw_status, "value", raw_status)
    can_post = bool(getattr(member, "can_post_messages", False))
    if status != "administrator" or not can_post:
        raise PostingRightsError(
            "Боту нужны права администратора канала с возможностью публиковать сообщения."
        )


async def publish_draft(bot: Any, repo: Repository, draft: DraftRecord) -> int | None:
    try:
        await ensure_bot_can_post(bot, draft.channel_id)
        markup = to_inline_keyboard_markup(deserialize_buttons(draft.buttons_json))
        if draft.overflow_text:
            sent = await bot.copy_message(
                chat_id=draft.channel_id,
                from_chat_id=draft.source_chat_id,
                message_id=draft.source_message_id,
                caption="",
            )
            await _send_overflow_text(bot, draft.channel_id, draft.overflow_text, markup)
        else:
            sent = await bot.copy_message(
                chat_id=draft.channel_id,
                from_chat_id=draft.source_chat_id,
                message_id=draft.source_message_id,
                reply_markup=markup,
            )
        message_id = getattr(sent, "message_id", None)
        await repo.mark_published(draft.id, message_id)
        return message_id
    except Exception as exc:
        await repo.mark_failed(draft.id, str(exc))
        if isinstance(exc, PublishError):
            raise
        if _is_caption_too_long_error(exc):
            raise PublishError(
                "Подпись к медиа длиннее лимита Telegram. Создайте черновик заново: "
                "бот сохранит длинную подпись отдельно и опубликует её текстом под медиа."
            ) from exc
        raise PublishError(str(exc)) from exc


async def _send_overflow_text(bot: Any, channel_id: int, text: str, markup: Any | None) -> None:
    chunks = split_telegram_text(text)
    for index, chunk in enumerate(chunks):
        is_last = index == len(chunks) - 1
        await bot.send_message(
            chat_id=channel_id,
            text=chunk,
            disable_web_page_preview=True,
            reply_markup=markup if is_last else None,
        )


def _is_caption_too_long_error(exc: Exception) -> bool:
    return "message caption is too long" in str(exc).lower()
