from __future__ import annotations

from typing import Any

from aiogram.exceptions import TelegramAPIError

from tgpostmaker.buttons import deserialize_buttons, to_inline_keyboard_markup
from tgpostmaker.db import DraftRecord, Repository


class PostingRightsError(RuntimeError):
    pass


class PublishError(RuntimeError):
    pass


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
        raise PublishError(str(exc)) from exc
