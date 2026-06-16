from __future__ import annotations

from datetime import UTC, datetime

from aiogram import F, Router
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message, ReplyKeyboardRemove

from tgpostmaker.buttons import (
    BUTTONS_INSTRUCTION,
    ButtonParseError,
    deserialize_buttons,
    parse_buttons,
    remove_button_at,
    serialize_buttons,
)
from tgpostmaker.config import Settings
from tgpostmaker.db import (
    STATUS_DRAFT,
    STATUS_PUBLISHED,
    STATUS_SCHEDULED,
    DraftRecord,
    Repository,
)
from tgpostmaker.keyboards import (
    CHANNEL_REQUEST_ID,
    channel_request_keyboard,
    channels_keyboard,
    delete_buttons_keyboard,
    draft_controls_keyboard,
    main_menu_keyboard,
)
from tgpostmaker.publisher import PostingRightsError, PublishError, ensure_bot_can_post, publish_draft
from tgpostmaker.schedule_parser import (
    ScheduleParseError,
    format_schedule,
    from_utc_iso,
    parse_schedule_input,
    to_utc_iso,
)
from tgpostmaker.states import AutopostStates


router = Router()


@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext, repo: Repository, settings: Settings) -> None:
    if not await _require_admin_message(message, settings):
        return
    await state.clear()
    await _send_start_menu(message, repo, settings)


@router.callback_query(F.data == "channel:list")
async def cb_channel_list(callback: CallbackQuery, repo: Repository, settings: Settings) -> None:
    if not await _require_admin_callback(callback, settings):
        return
    await callback.answer()
    if callback.message:
        await _send_channel_list(callback.message, repo, callback.from_user.id)


@router.callback_query(F.data == "channel:add")
async def cb_channel_add(callback: CallbackQuery, settings: Settings) -> None:
    if not await _require_admin_callback(callback, settings):
        return
    await callback.answer()
    if callback.message:
        await callback.message.answer(
            "Нажмите кнопку ниже и выберите канал. Telegram предложит выдать боту права администратора для публикаций.",
            reply_markup=channel_request_keyboard(),
        )


@router.callback_query(F.data.startswith("channel:select:"))
async def cb_channel_select(
    callback: CallbackQuery,
    bot,
    repo: Repository,
    settings: Settings,
) -> None:
    if not await _require_admin_callback(callback, settings):
        return

    channel_id = _parse_tail_int(callback.data)
    channel = await repo.get_channel(channel_id)
    if channel is None:
        await callback.answer("Канал не найден. Добавьте его заново.", show_alert=True)
        return

    try:
        await ensure_bot_can_post(bot, channel.chat_id)
    except PostingRightsError as exc:
        await callback.answer(str(exc), show_alert=True)
        return

    await repo.set_selected_channel(callback.from_user.id, channel.chat_id)
    await callback.answer("Канал выбран")
    if callback.message:
        await callback.message.edit_text(
            f"Выбран канал: {channel.title}",
            reply_markup=main_menu_keyboard(),
        )


@router.message(F.chat_shared)
async def message_chat_shared(message: Message, bot, repo: Repository, settings: Settings) -> None:
    if not await _require_admin_message(message, settings):
        return

    shared = message.chat_shared
    if shared is None or shared.request_id != CHANNEL_REQUEST_ID:
        return

    try:
        await ensure_bot_can_post(bot, shared.chat_id)
    except PostingRightsError as exc:
        await message.answer(
            f"{exc}\n\nДобавьте бота администратором канала и повторите выбор.",
            reply_markup=channel_request_keyboard(),
        )
        return

    title = getattr(shared, "title", None)
    username = getattr(shared, "username", None)
    if not title:
        chat = await bot.get_chat(shared.chat_id)
        title = getattr(chat, "title", None) or str(shared.chat_id)
        username = getattr(chat, "username", None)

    channel = await repo.upsert_channel(
        chat_id=shared.chat_id,
        title=title,
        username=username,
        added_by=message.from_user.id,
    )
    await repo.set_selected_channel(message.from_user.id, channel.chat_id)
    await message.answer(
        f"Канал выбран: {channel.title}",
        reply_markup=ReplyKeyboardRemove(),
    )
    await message.answer("Теперь можно создать пост.", reply_markup=main_menu_keyboard())


@router.callback_query(F.data == "autopost:start")
async def cb_autopost_start(
    callback: CallbackQuery,
    bot,
    state: FSMContext,
    repo: Repository,
    settings: Settings,
) -> None:
    if not await _require_admin_callback(callback, settings):
        return

    channel = await repo.get_selected_channel(callback.from_user.id)
    if channel is None:
        await callback.answer("Сначала выберите канал.", show_alert=True)
        if callback.message:
            await _send_channel_list(callback.message, repo, callback.from_user.id)
        return

    try:
        await ensure_bot_can_post(bot, channel.chat_id)
    except PostingRightsError as exc:
        await callback.answer(str(exc), show_alert=True)
        return

    await state.set_state(AutopostStates.waiting_post)
    await state.update_data(channel_id=channel.chat_id)
    await callback.answer()
    if callback.message:
        await callback.message.answer(
            "Пришлите пост одним сообщением: текст, фото, видео, документ или другое одиночное медиа с подписью."
        )


@router.message(AutopostStates.waiting_post)
async def message_waiting_post(message: Message, state: FSMContext, repo: Repository, settings: Settings) -> None:
    if not await _require_admin_message(message, settings):
        return

    if message.media_group_id:
        await message.answer("Альбомы пока не поддерживаются. Пришлите пост одним сообщением.")
        return
    if not _is_supported_post_message(message):
        await message.answer("Не могу использовать это как пост. Пришлите текст или одно медиа-сообщение.")
        return

    data = await state.get_data()
    channel_id = int(data["channel_id"])
    draft = await repo.create_draft(
        admin_id=message.from_user.id,
        channel_id=channel_id,
        source_chat_id=message.chat.id,
        source_message_id=message.message_id,
    )
    await state.clear()
    await message.answer(
        "Пост принят. Теперь можно добавить кнопки, запланировать или опубликовать.",
        reply_markup=draft_controls_keyboard(draft.id, has_buttons=False),
    )


@router.callback_query(F.data.startswith("draft:add:"))
async def cb_draft_add(callback: CallbackQuery, state: FSMContext, repo: Repository, settings: Settings) -> None:
    draft = await _get_editable_draft_from_callback(callback, repo, settings)
    if draft is None:
        return
    await state.set_state(AutopostStates.waiting_buttons_append)
    await state.update_data(draft_id=draft.id)
    await callback.answer()
    if callback.message:
        await callback.message.answer(BUTTONS_INSTRUCTION)


@router.callback_query(F.data.startswith("draft:edit:"))
async def cb_draft_edit(callback: CallbackQuery, state: FSMContext, repo: Repository, settings: Settings) -> None:
    draft = await _get_editable_draft_from_callback(callback, repo, settings)
    if draft is None:
        return
    await state.set_state(AutopostStates.waiting_buttons_replace)
    await state.update_data(draft_id=draft.id)
    await callback.answer()
    if callback.message:
        await callback.message.answer(
            f"Пришлите новый полный список кнопок.\n\n{BUTTONS_INSTRUCTION}"
        )


@router.message(AutopostStates.waiting_buttons_append)
async def message_buttons_append(message: Message, state: FSMContext, repo: Repository, settings: Settings) -> None:
    await _save_buttons_from_message(message, state, repo, settings, replace=False)


@router.message(AutopostStates.waiting_buttons_replace)
async def message_buttons_replace(message: Message, state: FSMContext, repo: Repository, settings: Settings) -> None:
    await _save_buttons_from_message(message, state, repo, settings, replace=True)


@router.callback_query(F.data.startswith("draft:delete:"))
async def cb_draft_delete(callback: CallbackQuery, repo: Repository, settings: Settings) -> None:
    draft = await _get_editable_draft_from_callback(callback, repo, settings)
    if draft is None:
        return
    rows = deserialize_buttons(draft.buttons_json)
    if not rows:
        await callback.answer("Кнопок пока нет.", show_alert=True)
        return
    await callback.answer()
    if callback.message:
        await callback.message.edit_text(
            "Выберите кнопку, которую нужно удалить:",
            reply_markup=delete_buttons_keyboard(draft.id, rows),
        )


@router.callback_query(F.data.startswith("button:delete:"))
async def cb_button_delete(callback: CallbackQuery, repo: Repository, settings: Settings) -> None:
    if not await _require_admin_callback(callback, settings):
        return

    _, _, raw_draft_id, raw_index = callback.data.split(":", 3)
    draft = await _get_editable_draft(callback, repo, int(raw_draft_id))
    if draft is None:
        return

    rows = deserialize_buttons(draft.buttons_json)
    try:
        rows = remove_button_at(rows, int(raw_index))
    except (IndexError, ValueError):
        await callback.answer("Кнопка уже недоступна.", show_alert=True)
        return

    draft = await repo.set_draft_buttons(draft.id, serialize_buttons(rows))
    await callback.answer("Кнопка удалена")
    if callback.message:
        if rows:
            await callback.message.edit_text(
                "Кнопка удалена. Можно удалить ещё одну или вернуться к управлению постом.",
                reply_markup=delete_buttons_keyboard(draft.id, rows),
            )
        else:
            await callback.message.edit_text(
                "Кнопки удалены.",
                reply_markup=draft_controls_keyboard(draft.id, has_buttons=False),
            )


@router.callback_query(F.data.startswith("draft:controls:"))
async def cb_draft_controls(callback: CallbackQuery, repo: Repository, settings: Settings) -> None:
    draft = await _get_editable_draft_from_callback(callback, repo, settings)
    if draft is None:
        return
    rows = deserialize_buttons(draft.buttons_json)
    await callback.answer()
    if callback.message:
        await callback.message.edit_text(
            "Управление постом:",
            reply_markup=draft_controls_keyboard(draft.id, bool(rows)),
        )


@router.callback_query(F.data.startswith("draft:schedule:"))
async def cb_draft_schedule(callback: CallbackQuery, state: FSMContext, repo: Repository, settings: Settings) -> None:
    draft = await _get_editable_draft_from_callback(callback, repo, settings)
    if draft is None:
        return
    await state.set_state(AutopostStates.waiting_schedule)
    await state.update_data(draft_id=draft.id)
    await callback.answer()
    if callback.message:
        await callback.message.answer(
            "Когда опубликовать пост?\n\nПримеры: сегодня 18:00, завтра 09:30, через 2 часа, 25.06 14:00."
        )


@router.message(AutopostStates.waiting_schedule)
async def message_schedule(message: Message, state: FSMContext, repo: Repository, settings: Settings) -> None:
    if not await _require_admin_message(message, settings):
        return
    if not message.text:
        await message.answer("Пришлите время текстом. Например: завтра 09:30.")
        return

    data = await state.get_data()
    draft_id = int(data["draft_id"])
    draft = await repo.get_draft(draft_id)
    if draft is None or draft.admin_id != message.from_user.id or draft.status != STATUS_DRAFT:
        await state.clear()
        await message.answer("Черновик уже недоступен.")
        return

    try:
        scheduled = parse_schedule_input(message.text, timezone_name=settings.timezone)
    except ScheduleParseError as exc:
        await message.answer(str(exc))
        return

    draft = await repo.set_schedule(draft.id, to_utc_iso(scheduled))
    await state.clear()
    rows = deserialize_buttons(draft.buttons_json)
    await message.answer(
        f"Время сохранено: {format_schedule(scheduled, settings.timezone)}.\nНажмите «Опубликовать», чтобы поставить пост в очередь.",
        reply_markup=draft_controls_keyboard(draft.id, bool(rows)),
    )


@router.callback_query(F.data.startswith("draft:publish:"))
async def cb_draft_publish(
    callback: CallbackQuery,
    bot,
    repo: Repository,
    settings: Settings,
) -> None:
    if not await _require_admin_callback(callback, settings):
        return

    draft_id = _parse_tail_int(callback.data)
    draft = await repo.get_draft(draft_id)
    if draft is None or draft.admin_id != callback.from_user.id:
        await callback.answer("Черновик не найден.", show_alert=True)
        return
    if draft.status == STATUS_PUBLISHED:
        await callback.answer("Пост уже опубликован.", show_alert=True)
        return
    if draft.status == STATUS_SCHEDULED:
        await callback.answer("Пост уже запланирован.", show_alert=True)
        return
    if draft.status != STATUS_DRAFT:
        await callback.answer("Черновик уже недоступен.", show_alert=True)
        return

    scheduled_at = from_utc_iso(draft.scheduled_at)
    if scheduled_at and scheduled_at > datetime.now(UTC):
        draft = await repo.mark_scheduled(draft.id)
        await callback.answer("Пост запланирован")
        if callback.message:
            await callback.message.edit_text(
                f"Пост запланирован на {format_schedule(scheduled_at, settings.timezone)}."
            )
        return

    await callback.answer()
    if callback.message:
        await callback.message.edit_text("Публикую пост...")
    try:
        await publish_draft(bot, repo, draft)
    except PublishError as exc:
        if callback.message:
            await callback.message.answer(f"Не удалось опубликовать пост:\n\n{exc}")
        return
    if callback.message:
        await callback.message.answer("Пост опубликован.")


async def _save_buttons_from_message(
    message: Message,
    state: FSMContext,
    repo: Repository,
    settings: Settings,
    *,
    replace: bool,
) -> None:
    if not await _require_admin_message(message, settings):
        return
    if not message.text:
        await message.answer(f"Пришлите кнопки текстом.\n\n{BUTTONS_INSTRUCTION}")
        return

    data = await state.get_data()
    draft_id = int(data["draft_id"])
    draft = await repo.get_draft(draft_id)
    if draft is None or draft.admin_id != message.from_user.id or draft.status != STATUS_DRAFT:
        await state.clear()
        await message.answer("Черновик уже недоступен.")
        return

    try:
        parsed_rows = parse_buttons(message.text)
    except ButtonParseError as exc:
        await message.answer(f"{exc}\n\n{BUTTONS_INSTRUCTION}")
        return

    current_rows = [] if replace else deserialize_buttons(draft.buttons_json)
    draft = await repo.set_draft_buttons(
        draft.id,
        serialize_buttons([*current_rows, *parsed_rows]),
    )
    await state.clear()
    await message.answer(
        "Кнопки сохранены.",
        reply_markup=draft_controls_keyboard(draft.id, has_buttons=True),
    )


async def _send_start_menu(message: Message, repo: Repository, settings: Settings) -> None:
    selected = await repo.get_selected_channel(message.from_user.id)
    if selected is not None:
        await message.answer(
            f"Выбран канал: {selected.title}",
            reply_markup=main_menu_keyboard(),
        )
        return

    await _send_channel_list(message, repo, message.from_user.id)


async def _send_channel_list(message: Message, repo: Repository, admin_id: int) -> None:
    channels = await repo.list_channels()
    selected = await repo.get_selected_channel(admin_id)
    if channels:
        await message.answer(
            "Выберите канал для публикации или добавьте новый.",
            reply_markup=channels_keyboard(
                channels,
                selected.chat_id if selected else None,
            ),
        )
    else:
        await message.answer(
            "Выберите канал для публикации. Telegram предложит выдать боту права администратора.",
            reply_markup=channel_request_keyboard(),
        )


async def _get_editable_draft_from_callback(
    callback: CallbackQuery,
    repo: Repository,
    settings: Settings,
) -> DraftRecord | None:
    if not await _require_admin_callback(callback, settings):
        return None
    return await _get_editable_draft(callback, repo, _parse_tail_int(callback.data))


async def _get_editable_draft(
    callback: CallbackQuery,
    repo: Repository,
    draft_id: int,
) -> DraftRecord | None:
    draft = await repo.get_draft(draft_id)
    if draft is None or draft.admin_id != callback.from_user.id:
        await callback.answer("Черновик не найден.", show_alert=True)
        return None
    if draft.status != STATUS_DRAFT:
        await callback.answer("Черновик уже нельзя редактировать.", show_alert=True)
        return None
    return draft


async def _require_admin_message(message: Message, settings: Settings) -> bool:
    user_id = message.from_user.id if message.from_user else None
    if user_id in settings.admin_ids:
        return True
    await message.answer("У вас нет доступа к этому боту.")
    return False


async def _require_admin_callback(callback: CallbackQuery, settings: Settings) -> bool:
    if callback.from_user.id in settings.admin_ids:
        return True
    await callback.answer("У вас нет доступа к этому боту.", show_alert=True)
    return False


def _parse_tail_int(data: str | None) -> int:
    if not data:
        raise ValueError("Callback data is empty")
    return int(data.rsplit(":", 1)[1])


def _is_supported_post_message(message: Message) -> bool:
    return any(
        (
            message.text,
            message.photo,
            message.video,
            message.document,
            message.animation,
            message.audio,
            message.voice,
            message.video_note,
        )
    )
