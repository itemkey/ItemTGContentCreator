from datetime import UTC, datetime, timedelta

import pytest

from tgpostmaker.buttons import parse_buttons, serialize_buttons
from tgpostmaker.db import STATUS_DRAFT, STATUS_PUBLISHED, STATUS_PUBLISHING, Repository


@pytest.mark.asyncio
async def test_channel_selection_and_draft_lifecycle(tmp_path) -> None:
    repo = Repository(str(tmp_path / "bot.db"))
    await repo.init()

    channel = await repo.upsert_channel(
        chat_id=-100123,
        title="Test Channel",
        username="test_channel",
        added_by=1,
    )
    await repo.set_selected_channel(1, channel.chat_id)

    selected = await repo.get_selected_channel(1)
    assert selected == channel

    draft = await repo.create_draft(
        admin_id=1,
        channel_id=channel.chat_id,
        source_chat_id=1,
        source_message_id=10,
        overflow_text="long caption",
    )
    assert draft.status == STATUS_DRAFT
    assert draft.overflow_text == "long caption"

    buttons_json = serialize_buttons(parse_buttons("Open - t.me/open"))
    draft = await repo.set_draft_buttons(draft.id, buttons_json)
    assert draft.buttons_json == buttons_json

    due_at = (datetime.now(UTC) - timedelta(minutes=1)).isoformat()
    draft = await repo.set_schedule(draft.id, due_at)
    await repo.mark_scheduled(draft.id)

    claimed = await repo.claim_due_draft(datetime.now(UTC).isoformat())
    assert claimed is not None
    assert claimed.status == STATUS_PUBLISHING

    await repo.mark_published(claimed.id, 77)
    published = await repo.get_draft(claimed.id)
    assert published is not None
    assert published.status == STATUS_PUBLISHED
    assert published.published_message_id == 77
