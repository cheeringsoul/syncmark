"""Telegram message persistence."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from .models import TelegramMessage


class TelegramRepo:
    async def upsert_message(self, session: AsyncSession, *, channel_id: int, channel_name: str, message_id: int, text: Optional[str], media_type: Optional[str], media_url: Optional[str], raw_json: Optional[dict], telegram_date: datetime) -> int:
        """
        @bodhi.intent Insert raw Telegram message, dedupe by (channel_id, message_id), return row id
        @bodhi.writes telegram_messages(channel_id, channel_name, message_id, text, media_type, media_url, raw_json, received_at, telegram_date) via INSERT ON CONFLICT DO NOTHING
        """
        stmt = (
            pg_insert(TelegramMessage)
            .values(
                channel_id=channel_id,
                channel_name=channel_name,
                message_id=message_id,
                text=text,
                media_type=media_type,
                media_url=media_url,
                raw_json=raw_json,
                received_at=datetime.now(timezone.utc),
                telegram_date=telegram_date,
            )
            .on_conflict_do_nothing(index_elements=["channel_id", "message_id"])
            .returning(TelegramMessage.id)
        )
        result = await session.execute(stmt)
        inserted_id = result.scalar_one_or_none()
        if inserted_id is not None:
            return inserted_id

        existing = await session.execute(
            select(TelegramMessage.id).where(
                TelegramMessage.channel_id == channel_id,
                TelegramMessage.message_id == message_id,
            )
        )
        return existing.scalar_one()
