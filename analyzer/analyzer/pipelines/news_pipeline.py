"""News pipeline — orchestrates Telegram raw to news ANALYZED to publish."""
from __future__ import annotations

import json
from datetime import datetime, timezone

import structlog
from sqlalchemy.ext.asyncio import async_sessionmaker

from ..db import session_scope
from ..llm.client import LLMClient, NewsAnalysis, rule_based_news_summary
from ..publisher.redis_publisher import RedisPublisher
from ..repository.ai_analysis_repo import AiAnalysisRepo
from ..repository.news_repo import NewsRepo
from ..repository.telegram_repo import TelegramRepo

log = structlog.get_logger(__name__)


def _coerce_int(value: str | None) -> int | None:
    if value in (None, ""):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _coerce_dt(value: str | None) -> datetime:
    if not value:
        return datetime.now(timezone.utc)
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return datetime.now(timezone.utc)


def _derive_title(text: str) -> str:
    snippet = (text or "").strip().split("\n", 1)[0]
    return snippet[:200] if snippet else "(no title)"


class NewsPipeline:
    def __init__(
        self,
        *,
        session_factory: async_sessionmaker,
        llm: LLMClient,
        publisher: RedisPublisher,
        telegram_repo: TelegramRepo,
        news_repo: NewsRepo,
        ai_analysis_repo: AiAnalysisRepo,
    ) -> None:
        self._session_factory = session_factory
        self._llm = llm
        self._publisher = publisher
        self._telegram_repo = telegram_repo
        self._news_repo = news_repo
        self._ai_analysis_repo = ai_analysis_repo

    async def handle(self, fields: dict[str, str]) -> None:
        """
        @bodhi.intent Handle one telegram raw message — persist, analyze, mark, publish
        @bodhi.calls TelegramRepo.upsert_message
        @bodhi.calls NewsRepo.create_raw
        @bodhi.calls NewsRepo.mark_analyzing
        @bodhi.calls NewsPipeline.run_analysis
        @bodhi.calls NewsRepo.mark_analyzed
        @bodhi.calls RedisPublisher.publish_news_analyzed
        @bodhi.on_fail llm_failure → degrade(rule_based_summary)
        @bodhi.on_fail db_failure → nack message → redeliver
        """
        channel_id = _coerce_int(fields.get("channel_id")) or 0
        message_id = _coerce_int(fields.get("message_id")) or 0
        channel_name = fields.get("channel_name", "")
        text = fields.get("text") or ""
        media_type = fields.get("media_type") or "none"
        media_url = fields.get("media_url") or None
        telegram_date = _coerce_dt(fields.get("telegram_date"))

        if not text and media_type == "none":
            log.info("skip_empty_message", channel_id=channel_id, message_id=message_id)
            return

        async with session_scope(self._session_factory) as session:
            tg_id = await self._telegram_repo.upsert_message(
                session,
                channel_id=channel_id,
                channel_name=channel_name,
                message_id=message_id,
                text=text,
                media_type=media_type,
                media_url=media_url,
                raw_json=dict(fields),
                telegram_date=telegram_date,
            )
            news_id = await self._news_repo.create_raw(
                session,
                source_type="telegram",
                source_message_id=tg_id,
                title=_derive_title(text),
                content=text,
            )
            await self._news_repo.mark_analyzing(session, news_id)

        try:
            analysis = await self.run_analysis(news_id=news_id, text=text, channel_name=channel_name)
        except Exception as exc:
            log.warning("llm_failed_using_fallback", news_id=news_id, error=str(exc))
            analysis = rule_based_news_summary(text)

        async with session_scope(self._session_factory) as session:
            await self._news_repo.mark_analyzed(
                session,
                news_id=news_id,
                ai_summary=analysis.summary,
                sentiment=analysis.sentiment,
                related_symbols=analysis.related_symbols,
                importance=analysis.importance,
            )

        await self._publisher.publish_news_analyzed(
            {
                "news_id": news_id,
                "title": _derive_title(text),
                "ai_summary": analysis.summary,
                "sentiment": analysis.sentiment,
                "related_symbols": analysis.related_symbols,
                "importance": analysis.importance,
                "analyzed_at": datetime.now(timezone.utc),
            }
        )

    async def run_analysis(self, *, news_id: int, text: str, channel_name: str) -> NewsAnalysis:
        """
        @bodhi.intent Call LLM to analyze a news message and persist audit row
        @bodhi.calls LLMClient.analyze_news
        @bodhi.calls AiAnalysisRepo.record
        @bodhi.on_fail llm_invalid_json → retry 1 → degrade(rule_based_summary)
        """
        analysis, llm_resp = await self._llm.analyze_news(text=text, channel_name=channel_name)
        async with session_scope(self._session_factory) as session:
            await self._ai_analysis_repo.record(
                session,
                ref_type="news",
                ref_id=news_id,
                prompt=text,
                response=json.dumps(
                    {
                        "summary": analysis.summary,
                        "sentiment": analysis.sentiment,
                        "related_symbols": analysis.related_symbols,
                        "importance": analysis.importance,
                    },
                    ensure_ascii=False,
                ),
                model=llm_resp.model,
                tokens_used=llm_resp.tokens_used,
                latency_ms=llm_resp.latency_ms,
            )
        return analysis
