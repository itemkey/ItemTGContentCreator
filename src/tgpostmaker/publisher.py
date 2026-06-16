from __future__ import annotations

from typing import Any

from aiogram.exceptions import TelegramAPIError

from tgpostmaker.buttons import deserialize_buttons, to_inline_keyboard_markup
from tgpostmaker.db import DraftRecord, Repository


TELEGRAM_CAPTION_LIMIT = 1024


class PostingRightsError(RuntimeError):
    pass


class PublishError(RuntimeError):
    pass


def extract_caption_overflow_text(message: Any) -> str | None:
    caption = getattr(message, "caption", None)
    if not caption or len(caption) <= TELEGRAM_CAPTION_LIMIT:
        return None
    return str(caption)


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
        sent = await _copy_draft_message(bot, draft, markup)
        message_id = getattr(sent, "message_id", None)
        await repo.mark_published(draft.id, message_id)
        return message_id
    except Exception as exc:
        await repo.mark_failed(draft.id, str(exc))
        if isinstance(exc, PublishError):
            raise
        if _is_caption_too_long_error(exc):
            raise PublishError(
                "Telegram не разрешил скопировать медиа с такой длинной подписью через Bot API."
            ) from exc
        raise PublishError(str(exc)) from exc


async def _copy_draft_message(bot: Any, draft: DraftRecord, markup: Any | None) -> Any:
    if draft.overflow_text:
        return await _copy_then_attach_markup(bot, draft, markup)

    try:
        return await bot.copy_message(
            chat_id=draft.channel_id,
            from_chat_id=draft.source_chat_id,
            message_id=draft.source_message_id,
            reply_markup=markup,
        )
    except Exception as exc:
        if markup is not None and _is_caption_too_long_error(exc):
            return await _copy_then_attach_markup(bot, draft, markup)
        raise


async def _copy_then_attach_markup(bot: Any, draft: DraftRecord, markup: Any | None) -> Any:
    sent = await bot.copy_message(
        chat_id=draft.channel_id,
        from_chat_id=draft.source_chat_id,
        message_id=draft.source_message_id,
    )
    message_id = getattr(sent, "message_id", None)
    if markup is not None and message_id is not None:
        await bot.edit_message_reply_markup(
            chat_id=draft.channel_id,
            message_id=message_id,
            reply_markup=markup,
        )
    return sent


def _is_caption_too_long_error(exc: Exception) -> bool:
    return "message caption is too long" in str(exc).lower()
