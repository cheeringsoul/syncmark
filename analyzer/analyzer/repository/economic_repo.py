"""Economic events persistence."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from .models import ECON_STATUS_PUBLISHED, EconomicEvent


@dataclass(frozen=True)
class EconomicEventInput:
    event_id: str
    name: str
    country: str
    importance: str
    scheduled_at: datetime
    previous: Optional[str]
    forecast: Optional[str]
    actual: Optional[str]
    status: int


class EconomicRepo:
    async def upsert(self, session: AsyncSession, ev: EconomicEventInput) -> int:
        """
        @bodhi.intent Idempotent upsert by event_id, return row id
        @bodhi.writes economic_events(event_id, name, country, importance, scheduled_at, previous, forecast, actual, status, updated_at) via INSERT ON CONFLICT (event_id) DO UPDATE
        """
        now = datetime.now(timezone.utc)
        stmt = pg_insert(EconomicEvent).values(
            event_id=ev.event_id,
            name=ev.name,
            country=ev.country,
            importance=ev.importance,
            scheduled_at=ev.scheduled_at,
            previous=ev.previous,
            forecast=ev.forecast,
            actual=ev.actual,
            status=ev.status,
            updated_at=now,
        )
        stmt = stmt.on_conflict_do_update(
            index_elements=["event_id"],
            set_={
                "name": stmt.excluded.name,
                "importance": stmt.excluded.importance,
                "scheduled_at": stmt.excluded.scheduled_at,
                "previous": stmt.excluded.previous,
                "forecast": stmt.excluded.forecast,
                "actual": stmt.excluded.actual,
                "status": stmt.excluded.status,
                "updated_at": now,
            },
        ).returning(EconomicEvent.id)
        result = await session.execute(stmt)
        return result.scalar_one()

    async def attach_analysis(self, session: AsyncSession, *, event_pk: int, ai_analysis: str) -> None:
        """
        @bodhi.intent Persist AI impact analysis on a published economic event
        @bodhi.writes economic_events(ai_analysis, updated_at) via UPDATE
        """
        await session.execute(
            update(EconomicEvent)
            .where(EconomicEvent.id == event_pk)
            .values(ai_analysis=ai_analysis, updated_at=datetime.now(timezone.utc))
        )

    async def recent_published(self, session: AsyncSession, limit: int = 10) -> list[EconomicEvent]:
        """
        @bodhi.intent Fetch recent published economic events for QA context
        @bodhi.reads economic_events(name, country, actual, forecast, previous, ai_analysis) WHERE status=PUBLISHED ORDER BY scheduled_at DESC LIMIT :limit
        """
        result = await session.execute(
            select(EconomicEvent)
            .where(EconomicEvent.status == ECON_STATUS_PUBLISHED)
            .order_by(EconomicEvent.scheduled_at.desc())
            .limit(limit)
        )
        return list(result.scalars().all())
