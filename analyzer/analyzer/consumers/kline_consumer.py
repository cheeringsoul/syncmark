"""CEX kline consumer — persists klines to PostgreSQL for historical analysis."""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation

import structlog
from sqlalchemy.ext.asyncio import async_sessionmaker, AsyncSession

from ..db import session_scope
from ..repository.kline_repo import KlineRepo
from .base import run_consumer_loop

log = structlog.get_logger(__name__)


def _decimal(v: str | None) -> Decimal:
    if not v:
        return Decimal(0)
    try:
        return Decimal(v)
    except InvalidOperation:
        return Decimal(0)


def _parse_ts(v: str | None) -> datetime:
    if not v:
        return datetime.now(timezone.utc)
    try:
        return datetime.fromisoformat(v)
    except ValueError:
        return datetime.now(timezone.utc)


class KlineConsumer:
    """XREADGROUP loop on cex:klines stream -> persist to PostgreSQL."""

    def __init__(
        self,
        *,
        redis_client,
        stream: str,
        group: str,
        consumer_id: str,
        dlq_stream: str,
        session_factory: async_sessionmaker[AsyncSession],
        kline_repo: KlineRepo,
    ) -> None:
        self._redis = redis_client
        self._stream = stream
        self._group = group
        self._consumer_id = consumer_id
        self._dlq_stream = dlq_stream
        self._session_factory = session_factory
        self._kline_repo = kline_repo

    async def run(self) -> None:
        """
        @bodhi.intent XREADGROUP loop on cex:klines stream, persist each kline to PostgreSQL
        @bodhi.consumes cex_kline(exchange, symbol, interval, open, high, low, close, volume, quote_volume, open_time, close_time) from redis:cex:klines
        @bodhi.calls KlineRepo.upsert
        """
        await run_consumer_loop(
            client=self._redis,
            stream=self._stream,
            group=self._group,
            consumer=self._consumer_id,
            handler=self._handle,
            dlq_stream=self._dlq_stream,
        )

    async def _handle(self, fields: dict[str, str]) -> None:
        """
        @bodhi.intent Parse kline fields from stream message and upsert to database
        @bodhi.reads redis:cex:klines message fields
        @bodhi.calls KlineRepo.upsert
        """
        import json

        # The collector publishes kline as a JSON blob in the "data" field
        raw = fields.get("data")
        if raw:
            data = json.loads(raw)
        else:
            data = fields

        async with session_scope(self._session_factory) as session:
            await self._kline_repo.upsert(
                session,
                exchange=data.get("exchange", ""),
                symbol=data.get("symbol", ""),
                interval=data.get("interval", ""),
                open_time=_parse_ts(data.get("open_time")),
                open=_decimal(data.get("open")),
                high=_decimal(data.get("high")),
                low=_decimal(data.get("low")),
                close=_decimal(data.get("close")),
                volume=_decimal(data.get("volume")),
                quote_volume=_decimal(data.get("quote_volume")),
                close_time=_parse_ts(data.get("close_time")),
            )
