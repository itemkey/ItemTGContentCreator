from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime, timedelta
from typing import Any

from tgpostmaker.db import Repository
from tgpostmaker.publisher import PublishError, publish_draft


logger = logging.getLogger(__name__)


async def scheduler_loop(
    *,
    bot: Any,
    repo: Repository,
    interval_seconds: float,
    stale_after: timedelta = timedelta(minutes=15),
) -> None:
    await repo.recover_stale_publishing(stale_after=stale_after)

    while True:
        await publish_due_drafts(bot=bot, repo=repo)
        await asyncio.sleep(interval_seconds)


async def publish_due_drafts(*, bot: Any, repo: Repository) -> int:
    published = 0
    while True:
        draft = await repo.claim_due_draft(datetime.now(UTC).isoformat())
        if draft is None:
            return published

        try:
            await publish_draft(bot, repo, draft)
            published += 1
        except PublishError as exc:
            logger.warning("Scheduled draft %s failed: %s", draft.id, exc)
            await _notify_admin(bot, draft.admin_id, draft.id, str(exc))


async def _notify_admin(bot: Any, admin_id: int, draft_id: int, error_text: str) -> None:
    try:
        await bot.send_message(
            admin_id,
            f"Не удалось опубликовать запланированный пост #{draft_id}.\n\n{error_text}",
        )
    except Exception:
        logger.exception("Failed to notify admin %s about draft %s", admin_id, draft_id)

