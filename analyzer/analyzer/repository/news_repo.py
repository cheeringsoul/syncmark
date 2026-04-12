"""News record persistence and lifecycle transitions."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from .models import (
    NEWS_STATUS_ANALYZED,
    NEWS_STATUS_ANALYZING,
    NEWS_STATUS_RAW,
    News,
)


class NewsRepo:
    async def create_raw(self, session: AsyncSession, *, source_type: str, source_message_id: Optional[int], title: Optional[str], content: Optional[str]) -> int:
        """
        @bodhi.intent Create news row in RAW status, return id
        @bodhi.writes news(source_type, source_message_id, title, content, status=RAW, created_at) via INSERT
        """
        row = News(
            source_type=source_type,
            source_message_id=source_message_id,
            title=title,
            content=content,
            status=NEWS_STATUS_RAW,
            created_at=datetime.now(timezone.utc),
        )
        session.add(row)
        await session.flush()
        return row.id

    async def mark_analyzing(self, session: AsyncSession, news_id: int) -> None:
        """
        @bodhi.intent Transition news RAW to ANALYZING before invoking LLM
        @bodhi.writes news(status=ANALYZING) via UPDATE
        """
        await session.execute(
            update(News).where(News.id == news_id).values(status=NEWS_STATUS_ANALYZING)
        )

    async def mark_analyzed(self, session: AsyncSession, *, news_id: int, ai_summary: str, sentiment: str, related_symbols: list[str], importance: str) -> None:
        """
        @bodhi.intent Apply analysis fields, transition news ANALYZING to ANALYZED
        @bodhi.writes news(ai_summary, sentiment, related_symbols, importance, status=ANALYZED, analyzed_at) via UPDATE
        """
        await session.execute(
            update(News)
            .where(News.id == news_id)
            .values(
                ai_summary=ai_summary,
                sentiment=sentiment,
                related_symbols=related_symbols,
                importance=importance,
                status=NEWS_STATUS_ANALYZED,
                analyzed_at=datetime.now(timezone.utc),
            )
        )

