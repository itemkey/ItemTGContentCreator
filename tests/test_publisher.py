from dataclasses import dataclass

import pytest

from tgpostmaker.buttons import parse_buttons, serialize_buttons
from tgpostmaker.db import STATUS_FAILED, STATUS_PUBLISHED, Repository
from tgpostmaker.publisher import (
    PostingRightsError,
    ensure_bot_can_post,
    extract_caption_overflow_text,
    publish_draft,
    split_telegram_text,
)


@dataclass
class FakeUser:
    id: int


@dataclass
class FakeMember:
    status: str
    can_post_messages: bool


@dataclass
class FakeSentMessage:
    message_id: int


class FakeBot:
    def __init__(self, *, can_post: bool = True) -> None:
        self.can_post = can_post
        self.copied: dict | None = None
        self.sent_messages: list[dict] = []

    async def get_me(self) -> FakeUser:
        return FakeUser(id=42)

    async def get_chat_member(self, channel_id: int, user_id: int) -> FakeMember:
        return FakeMember(status="administrator", can_post_messages=self.can_post)

    async def copy_message(self, **kwargs) -> FakeSentMessage:
        self.copied = kwargs
        return FakeSentMessage(message_id=555)

    async def send_message(self, **kwargs) -> FakeSentMessage:
        self.sent_messages.append(kwargs)
        return FakeSentMessage(message_id=777 + len(self.sent_messages))


@dataclass
class FakeIncomingMessage:
    caption: str | None = None


@pytest.mark.asyncio
async def test_ensure_bot_can_post_rejects_missing_right() -> None:
    with pytest.raises(PostingRightsError):
        await ensure_bot_can_post(FakeBot(can_post=False), -100123)


@pytest.mark.asyncio
async def test_publish_draft_copies_message_and_marks_published(tmp_path) -> None:
    repo = Repository(str(tmp_path / "bot.db"))
    await repo.init()
    channel = await repo.upsert_channel(
        chat_id=-100123,
        title="Channel",
        username=None,
        added_by=1,
    )
    draft = await repo.create_draft(
        admin_id=1,
        channel_id=channel.chat_id,
        source_chat_id=1,
        source_message_id=10,
        buttons_json=serialize_buttons(parse_buttons("Go - t.me/go")),
    )

    bot = FakeBot()
    message_id = await publish_draft(bot, repo, draft)

    assert message_id == 555
    assert bot.copied is not None
    assert bot.copied["chat_id"] == channel.chat_id
    assert bot.copied["from_chat_id"] == 1
    assert bot.copied["message_id"] == 10
    assert bot.copied["reply_markup"] is not None

    stored = await repo.get_draft(draft.id)
    assert stored is not None
    assert stored.status == STATUS_PUBLISHED


@pytest.mark.asyncio
async def test_publish_draft_moves_long_caption_to_text_message(tmp_path) -> None:
    repo = Repository(str(tmp_path / "bot.db"))
    await repo.init()
    channel = await repo.upsert_channel(
        chat_id=-100123,
        title="Channel",
        username=None,
        added_by=1,
    )
    draft = await repo.create_draft(
        admin_id=1,
        channel_id=channel.chat_id,
        source_chat_id=1,
        source_message_id=10,
        buttons_json=serialize_buttons(parse_buttons("Go - t.me/go")),
        overflow_text="x" * 1025,
    )

    bot = FakeBot()
    message_id = await publish_draft(bot, repo, draft)

    assert message_id == 555
    assert bot.copied is not None
    assert bot.copied["caption"] == ""
    assert "reply_markup" not in bot.copied
    assert len(bot.sent_messages) == 1
    assert bot.sent_messages[0]["chat_id"] == channel.chat_id
    assert bot.sent_messages[0]["text"] == "x" * 1025
    assert bot.sent_messages[0]["reply_markup"] is not None

    stored = await repo.get_draft(draft.id)
    assert stored is not None
    assert stored.status == STATUS_PUBLISHED


def test_extract_caption_overflow_text_uses_caption_limit() -> None:
    assert extract_caption_overflow_text(FakeIncomingMessage(caption="x" * 1024)) is None
    assert extract_caption_overflow_text(FakeIncomingMessage(caption="x" * 1025)) == "x" * 1025


def test_split_telegram_text_respects_message_limit() -> None:
    chunks = split_telegram_text(("x" * 4096) + " " + ("y" * 10))

    assert chunks == ["x" * 4096, "y" * 10]


@pytest.mark.asyncio
async def test_publish_draft_marks_failed_on_missing_rights(tmp_path) -> None:
    repo = Repository(str(tmp_path / "bot.db"))
    await repo.init()
    channel = await repo.upsert_channel(
        chat_id=-100123,
        title="Channel",
        username=None,
        added_by=1,
    )
    draft = await repo.create_draft(
        admin_id=1,
        channel_id=channel.chat_id,
        source_chat_id=1,
        source_message_id=10,
    )

    with pytest.raises(Exception):
        await publish_draft(FakeBot(can_post=False), repo, draft)

    stored = await repo.get_draft(draft.id)
    assert stored is not None
    assert stored.status == STATUS_FAILED
