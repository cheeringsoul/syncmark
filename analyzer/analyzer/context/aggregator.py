"""Context aggregator for AI Q&A — pulls recent news, macro, ticker snapshots."""
from __future__ import annotations

import structlog
import redis.asyncio as redis
from sqlalchemy.ext.asyncio import async_sessionmaker

from ..db import session_scope
from ..repository.economic_repo import EconomicRepo
from ..repository.news_query import NewsQuery

log = structlog.get_logger(__name__)

DEFAULT_TICKER_KEYS = [
    "ticker:binance:BTCUSDT",
    "ticker:binance:ETHUSDT",
    "ticker:binance:SOLUSDT",
]


class ContextAggregator:
    def __init__(
        self,
        *,
        session_factory: async_sessionmaker,
        redis_client: redis.Redis,
        news_query: NewsQuery,
        economic_repo: EconomicRepo,
    ) -> None:
        self._session_factory = session_factory
        self._redis = redis_client
        self._news_query = news_query
        self._economic_repo = economic_repo

    async def collect(self) -> list[str]:
        """
        @bodhi.intent Aggregate recent news, top tickers, and recent macro events into prompt context blocks
        @bodhi.calls NewsQuery.recent_analyzed
        @bodhi.calls EconomicRepo.recent_published
        @bodhi.reads redis:ticker(price, change_24h)
        """
        blocks: list[str] = []
        blocks.append(await self._news_block())
        blocks.append(await self._macro_block())
        blocks.append(await self._ticker_block())
        return [b for b in blocks if b]

    async def _news_block(self) -> str:
        async with session_scope(self._session_factory) as session:
            rows = await self._news_query.recent_analyzed(session, hours=24, limit=20)
        if not rows:
            return ""
        lines = ["[最近 24h 快讯]"]
        for n in rows:
            symbols = ",".join(n.related_symbols or [])
            lines.append(
                f"- ({n.sentiment or 'neutral'}/{symbols}) {n.ai_summary or n.title or ''}"
            )
        return "\n".join(lines)

    async def _macro_block(self) -> str:
        async with session_scope(self._session_factory) as session:
            rows = await self._economic_repo.recent_published(session, limit=10)
        if not rows:
            return ""
        lines = ["[最近经济数据]"]
        for ev in rows:
            lines.append(
                f"- {ev.name}({ev.country}) 实际={ev.actual} 预期={ev.forecast} → {ev.ai_analysis or ''}"
            )
        return "\n".join(lines)

    async def _ticker_block(self) -> str:
        lines = ["[当前行情]"]
        any_found = False
        for key in DEFAULT_TICKER_KEYS:
            try:
                snapshot = await self._redis.hgetall(key)
            except Exception as exc:
                log.warning("ticker_read_failed", key=key, error=str(exc))
                continue
            if not snapshot:
                continue
            any_found = True
            symbol = key.split(":")[-1]
            lines.append(
                f"- {symbol} price={snapshot.get('price', '?')} 24h={snapshot.get('change_24h', '?')}"
            )
        return "\n".join(lines) if any_found else ""
