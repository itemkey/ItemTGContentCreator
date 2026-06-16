from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import aiosqlite


STATUS_DRAFT = "draft"
STATUS_SCHEDULED = "scheduled"
STATUS_PUBLISHING = "publishing"
STATUS_PUBLISHED = "published"
STATUS_FAILED = "failed"


@dataclass(frozen=True)
class ChannelRecord:
    chat_id: int
    title: str
    username: str | None
    added_by: int
    created_at: str
    updated_at: str


@dataclass(frozen=True)
class DraftRecord:
    id: int
    admin_id: int
    channel_id: int
    source_chat_id: int
    source_message_id: int
    buttons_json: str
    scheduled_at: str | None
    status: str
    locked_at: str | None
    published_message_id: int | None
    created_at: str
    updated_at: str


class Repository:
    def __init__(self, db_path: str) -> None:
        self.db_path = db_path

    async def init(self) -> None:
        path = Path(self.db_path)
        if path.parent:
            path.parent.mkdir(parents=True, exist_ok=True)

        async with self._connect() as db:
            await db.executescript(
                """
                PRAGMA journal_mode = WAL;

                CREATE TABLE IF NOT EXISTS channels (
                    chat_id INTEGER PRIMARY KEY,
                    title TEXT NOT NULL,
                    username TEXT,
                    added_by INTEGER NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS admin_settings (
                    admin_id INTEGER PRIMARY KEY,
                    selected_channel_id INTEGER,
                    updated_at TEXT NOT NULL,
                    FOREIGN KEY(selected_channel_id) REFERENCES channels(chat_id)
                );

                CREATE TABLE IF NOT EXISTS drafts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    admin_id INTEGER NOT NULL,
                    channel_id INTEGER NOT NULL,
                    source_chat_id INTEGER NOT NULL,
                    source_message_id INTEGER NOT NULL,
                    buttons_json TEXT NOT NULL DEFAULT '[]',
                    scheduled_at TEXT,
                    status TEXT NOT NULL,
                    locked_at TEXT,
                    published_message_id INTEGER,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    FOREIGN KEY(channel_id) REFERENCES channels(chat_id)
                );

                CREATE INDEX IF NOT EXISTS idx_drafts_status_schedule
                    ON drafts(status, scheduled_at);

                CREATE TABLE IF NOT EXISTS publish_attempts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    draft_id INTEGER NOT NULL,
                    status TEXT NOT NULL,
                    error_text TEXT,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(draft_id) REFERENCES drafts(id)
                );
                """
            )
            await db.commit()

    async def upsert_channel(
        self,
        *,
        chat_id: int,
        title: str,
        username: str | None,
        added_by: int,
    ) -> ChannelRecord:
        now = utc_now_iso()
        async with self._connect() as db:
            await db.execute(
                """
                INSERT INTO channels(chat_id, title, username, added_by, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(chat_id) DO UPDATE SET
                    title = excluded.title,
                    username = excluded.username,
                    added_by = excluded.added_by,
                    updated_at = excluded.updated_at
                """,
                (chat_id, title, username, added_by, now, now),
            )
            await db.commit()
        return await self.get_channel(chat_id)  # type: ignore[return-value]

    async def list_channels(self) -> list[ChannelRecord]:
        async with self._connect() as db:
            rows = await _fetchall(db, "SELECT * FROM channels ORDER BY lower(title), chat_id")
        return [_channel_from_row(row) for row in rows]

    async def get_channel(self, chat_id: int) -> ChannelRecord | None:
        async with self._connect() as db:
            row = await _fetchone(
                db,
                "SELECT * FROM channels WHERE chat_id = ?",
                (chat_id,),
            )
        return _channel_from_row(row) if row else None

    async def set_selected_channel(self, admin_id: int, channel_id: int) -> None:
        now = utc_now_iso()
        async with self._connect() as db:
            await db.execute(
                """
                INSERT INTO admin_settings(admin_id, selected_channel_id, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(admin_id) DO UPDATE SET
                    selected_channel_id = excluded.selected_channel_id,
                    updated_at = excluded.updated_at
                """,
                (admin_id, channel_id, now),
            )
            await db.commit()

    async def get_selected_channel(self, admin_id: int) -> ChannelRecord | None:
        async with self._connect() as db:
            row = await _fetchone(
                db,
                """
                SELECT channels.*
                FROM admin_settings
                JOIN channels ON channels.chat_id = admin_settings.selected_channel_id
                WHERE admin_settings.admin_id = ?
                """,
                (admin_id,),
            )
        return _channel_from_row(row) if row else None

    async def create_draft(
        self,
        *,
        admin_id: int,
        channel_id: int,
        source_chat_id: int,
        source_message_id: int,
        buttons_json: str = "[]",
    ) -> DraftRecord:
        now = utc_now_iso()
        async with self._connect() as db:
            cursor = await db.execute(
                """
                INSERT INTO drafts(
                    admin_id, channel_id, source_chat_id, source_message_id,
                    buttons_json, status, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    admin_id,
                    channel_id,
                    source_chat_id,
                    source_message_id,
                    buttons_json,
                    STATUS_DRAFT,
                    now,
                    now,
                ),
            )
            await db.commit()
            draft_id = int(cursor.lastrowid)
        return await self.get_draft(draft_id)  # type: ignore[return-value]

    async def get_draft(self, draft_id: int) -> DraftRecord | None:
        async with self._connect() as db:
            row = await _fetchone(
                db,
                "SELECT * FROM drafts WHERE id = ?",
                (draft_id,),
            )
        return _draft_from_row(row) if row else None

    async def set_draft_buttons(self, draft_id: int, buttons_json: str) -> DraftRecord:
        await self._update_draft(
            draft_id,
            "buttons_json = ?, updated_at = ?",
            (buttons_json, utc_now_iso()),
        )
        return await self.get_draft(draft_id)  # type: ignore[return-value]

    async def set_schedule(self, draft_id: int, scheduled_at: str) -> DraftRecord:
        await self._update_draft(
            draft_id,
            "scheduled_at = ?, updated_at = ?",
            (scheduled_at, utc_now_iso()),
        )
        return await self.get_draft(draft_id)  # type: ignore[return-value]

    async def mark_scheduled(self, draft_id: int) -> DraftRecord:
        await self._update_draft(
            draft_id,
            "status = ?, locked_at = NULL, updated_at = ?",
            (STATUS_SCHEDULED, utc_now_iso()),
        )
        return await self.get_draft(draft_id)  # type: ignore[return-value]

    async def mark_published(self, draft_id: int, message_id: int | None) -> None:
        await self._update_draft(
            draft_id,
            "status = ?, published_message_id = ?, locked_at = NULL, updated_at = ?",
            (STATUS_PUBLISHED, message_id, utc_now_iso()),
        )
        await self.log_publish_attempt(draft_id, STATUS_PUBLISHED, None)

    async def mark_failed(self, draft_id: int, error_text: str) -> None:
        await self._update_draft(
            draft_id,
            "status = ?, locked_at = NULL, updated_at = ?",
            (STATUS_FAILED, utc_now_iso()),
        )
        await self.log_publish_attempt(draft_id, STATUS_FAILED, error_text)

    async def log_publish_attempt(
        self,
        draft_id: int,
        status: str,
        error_text: str | None,
    ) -> None:
        async with self._connect() as db:
            await db.execute(
                """
                INSERT INTO publish_attempts(draft_id, status, error_text, created_at)
                VALUES (?, ?, ?, ?)
                """,
                (draft_id, status, error_text, utc_now_iso()),
            )
            await db.commit()

    async def claim_due_draft(self, now_iso: str) -> DraftRecord | None:
        locked_at = utc_now_iso()
        async with self._connect() as db:
            await db.execute("BEGIN IMMEDIATE")
            row = await _fetchone(
                db,
                """
                SELECT * FROM drafts
                WHERE status = ?
                  AND scheduled_at IS NOT NULL
                  AND scheduled_at <= ?
                ORDER BY scheduled_at ASC, id ASC
                LIMIT 1
                """,
                (STATUS_SCHEDULED, now_iso),
            )
            if row is None:
                await db.commit()
                return None

            draft_id = int(row["id"])
            await db.execute(
                """
                UPDATE drafts
                SET status = ?, locked_at = ?, updated_at = ?
                WHERE id = ?
                """,
                (STATUS_PUBLISHING, locked_at, locked_at, draft_id),
            )
            await db.commit()

        return await self.get_draft(draft_id)

    async def recover_stale_publishing(self, *, stale_after: timedelta) -> int:
        stale_before = (datetime.now(UTC) - stale_after).isoformat()
        async with self._connect() as db:
            cursor = await db.execute(
                """
                UPDATE drafts
                SET status = ?, locked_at = NULL, updated_at = ?
                WHERE status = ?
                  AND locked_at IS NOT NULL
                  AND locked_at < ?
                """,
                (STATUS_SCHEDULED, utc_now_iso(), STATUS_PUBLISHING, stale_before),
            )
            await db.commit()
            return cursor.rowcount

    async def _update_draft(
        self,
        draft_id: int,
        set_sql: str,
        values: tuple[Any, ...],
    ) -> None:
        async with self._connect() as db:
            await db.execute(
                f"UPDATE drafts SET {set_sql} WHERE id = ?",
                (*values, draft_id),
            )
            await db.commit()

    @asynccontextmanager
    async def _connect(self) -> AsyncIterator[aiosqlite.Connection]:
        db = await aiosqlite.connect(self.db_path)
        db.row_factory = aiosqlite.Row
        await db.execute("PRAGMA foreign_keys = ON")
        try:
            yield db
        finally:
            await db.close()


def utc_now_iso() -> str:
    return datetime.now(UTC).isoformat()


async def _fetchone(
    db: aiosqlite.Connection,
    sql: str,
    params: tuple[Any, ...] = (),
) -> aiosqlite.Row | None:
    async with db.execute(sql, params) as cursor:
        return await cursor.fetchone()


async def _fetchall(
    db: aiosqlite.Connection,
    sql: str,
    params: tuple[Any, ...] = (),
) -> list[aiosqlite.Row]:
    async with db.execute(sql, params) as cursor:
        return await cursor.fetchall()


def _channel_from_row(row: aiosqlite.Row) -> ChannelRecord:
    return ChannelRecord(
        chat_id=int(row["chat_id"]),
        title=str(row["title"]),
        username=row["username"],
        added_by=int(row["added_by"]),
        created_at=str(row["created_at"]),
        updated_at=str(row["updated_at"]),
    )


def _draft_from_row(row: aiosqlite.Row) -> DraftRecord:
    return DraftRecord(
        id=int(row["id"]),
        admin_id=int(row["admin_id"]),
        channel_id=int(row["channel_id"]),
        source_chat_id=int(row["source_chat_id"]),
        source_message_id=int(row["source_message_id"]),
        buttons_json=str(row["buttons_json"]),
        scheduled_at=row["scheduled_at"],
        status=str(row["status"]),
        locked_at=row["locked_at"],
        published_message_id=row["published_message_id"],
        created_at=str(row["created_at"]),
        updated_at=str(row["updated_at"]),
    )
