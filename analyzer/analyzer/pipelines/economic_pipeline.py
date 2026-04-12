"""Economic event pipeline — upsert + AI impact analysis when published."""
from __future__ import annotations

from datetime import datetime, timezone

import structlog
from sqlalchemy.ext.asyncio import async_sessionmaker

from ..db import session_scope
from ..llm.client import LLMClient
from ..publisher.redis_publisher import RedisPublisher
from ..repository.ai_analysis_repo import AiAnalysisRepo
from ..repository.economic_repo import EconomicEventInput, EconomicRepo
from ..repository.models import ECON_STATUS_PUBLISHED

log = structlog.get_logger(__name__)


_STATUS_MAP = {
    "scheduled": 0,
    "upcoming": 1,
    "published": 2,
}


def _coerce_dt(value: str | None) -> datetime:
    if not value:
        return datetime.now(timezone.utc)
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return datetime.now(timezone.utc)


class EconomicPipeline:
    def __init__(
        self,
        *,
        session_factory: async_sessionmaker,
        llm: LLMClient,
        publisher: RedisPublisher,
        economic_repo: EconomicRepo,
        ai_analysis_repo: AiAnalysisRepo,
    ) -> None:
        self._session_factory = session_factory
        self._llm = llm
        self._publisher = publisher
        self._economic_repo = economic_repo
        self._ai_analysis_repo = ai_analysis_repo

    async def handle(self, fields: dict[str, str]) -> None:
        """
        @bodhi.intent Upsert economic event; if PUBLISHED, run AI impact analysis and publish downstream
        @bodhi.calls EconomicRepo.upsert
        @bodhi.calls EconomicPipeline.maybe_analyze
        @bodhi.on_fail db_failure → nack → redeliver
        """
        status_str = (fields.get("status") or "scheduled").lower()
        status = _STATUS_MAP.get(status_str, 0)

        ev = EconomicEventInput(
            event_id=fields.get("event_id", ""),
            name=fields.get("name", ""),
            country=fields.get("country", ""),
            importance=fields.get("importance", "low"),
            scheduled_at=_coerce_dt(fields.get("scheduled_at")),
            previous=fields.get("previous") or None,
            forecast=fields.get("forecast") or None,
            actual=fields.get("actual") or None,
            status=status,
        )
        if not ev.event_id:
            log.warning("skip_event_no_id", fields=fields)
            return

        async with session_scope(self._session_factory) as session:
            row_id = await self._economic_repo.upsert(session, ev)

        if status == ECON_STATUS_PUBLISHED and ev.actual:
            await self.maybe_analyze(row_id=row_id, ev=ev)

    async def maybe_analyze(self, *, row_id: int, ev: EconomicEventInput) -> None:
        """
        @bodhi.intent Run AI analysis on a published macro event, persist, emit downstream
        @bodhi.calls LLMClient.analyze_macro
        @bodhi.calls EconomicRepo.attach_analysis
        @bodhi.calls AiAnalysisRepo.record
        @bodhi.calls RedisPublisher.publish_economic_analyzed
        @bodhi.on_fail llm_timeout → degrade(skip_ai)
        """
        try:
            llm_resp = await self._llm.analyze_macro(
                name=ev.name,
                country=ev.country,
                previous=ev.previous,
                forecast=ev.forecast,
                actual=ev.actual,
            )
        except Exception as exc:
            log.warning("macro_llm_failed", event_id=ev.event_id, error=str(exc))
            return

        ai_analysis = llm_resp.text.strip()
        async with session_scope(self._session_factory) as session:
            await self._economic_repo.attach_analysis(
                session, event_pk=row_id, ai_analysis=ai_analysis
            )
            await self._ai_analysis_repo.record(
                session,
                ref_type="economic_event",
                ref_id=row_id,
                prompt=f"{ev.name} prev={ev.previous} fcst={ev.forecast} actual={ev.actual}",
                response=ai_analysis,
                model=llm_resp.model,
                tokens_used=llm_resp.tokens_used,
                latency_ms=llm_resp.latency_ms,
            )

        await self._publisher.publish_economic_analyzed(
            {
                "event_id": ev.event_id,
                "name": ev.name,
                "country": ev.country,
                "actual": ev.actual,
                "forecast": ev.forecast,
                "previous": ev.previous,
                "ai_analysis": ai_analysis,
                "importance": ev.importance,
                "published_at": datetime.now(timezone.utc),
            }
        )
