from __future__ import annotations

import asyncio
import logging
from contextlib import suppress

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.fsm.storage.memory import MemoryStorage

from tgpostmaker.config import load_settings
from tgpostmaker.db import Repository
from tgpostmaker.handlers import router
from tgpostmaker.scheduler import scheduler_loop


async def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    settings = load_settings()
    repo = Repository(settings.db_path)
    await repo.init()

    bot = Bot(
        token=settings.bot_token,
        default=DefaultBotProperties(parse_mode=None),
    )
    dp = Dispatcher(storage=MemoryStorage())
    dp.include_router(router)

    scheduler_task = asyncio.create_task(
        scheduler_loop(
            bot=bot,
            repo=repo,
            interval_seconds=settings.scheduler_interval_seconds,
        )
    )
    try:
        await bot.delete_webhook(drop_pending_updates=True)
        await dp.start_polling(bot, repo=repo, settings=settings)
    finally:
        scheduler_task.cancel()
        with suppress(asyncio.CancelledError):
            await scheduler_task
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())

