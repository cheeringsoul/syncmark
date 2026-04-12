"""News read queries used by the AI Q&A context aggregator."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .models import NEWS_STATUS_ANALYZED, News


class NewsQuery:
    async def recent_analyzed(self, session: AsyncSession, hours: int = 24, limit: int = 30) -> list[News]:
        """
        @bodhi.intent Fetch recent ANALYZED news rows for QA prompt context
        @bodhi.reads news(id, title, ai_summary, sentiment, related_symbols, published_at) WHERE status>=ANALYZED AND created_at > now() - :hours ORDER BY created_at DESC LIMIT :limit
        """
        cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
        result = await session.execute(
            select(News)
            .where(News.status >= NEWS_STATUS_ANALYZED, News.created_at > cutoff)
            .order_by(News.created_at.desc())
            .limit(limit)
        )
        return list(result.scalars().all())
