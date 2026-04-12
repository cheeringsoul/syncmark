"""Kline persistence and query for rotation analysis."""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from .models import Kline


class KlineRepo:
    async def upsert(
        self,
        session: AsyncSession,
        *,
        exchange: str,
        symbol: str,
        interval: str,
        open_time: datetime,
        open: Decimal,
        high: Decimal,
        low: Decimal,
        close: Decimal,
        volume: Decimal,
        quote_volume: Decimal,
        close_time: datetime,
    ) -> None:
        """
        @bodhi.intent Upsert kline record — idempotent on unique constraint (exchange, symbol, interval, open_time)
        @bodhi.writes klines(exchange, symbol, interval, open, high, low, close, volume, quote_volume, open_time, close_time) via UPSERT
        @bodhi.on_fail duplicate → skip (idempotent)
        """
        stmt = pg_insert(Kline).values(
            exchange=exchange,
            symbol=symbol,
            interval=interval,
            open_time=open_time,
            open=open,
            high=high,
            low=low,
            close=close,
            volume=volume,
            quote_volume=quote_volume,
            close_time=close_time,
        )
        stmt = stmt.on_conflict_do_update(
            constraint="uq_kline",
            set_={
                "high": stmt.excluded.high,
                "low": stmt.excluded.low,
                "close": stmt.excluded.close,
                "volume": stmt.excluded.volume,
                "quote_volume": stmt.excluded.quote_volume,
                "close_time": stmt.excluded.close_time,
            },
        )
        await session.execute(stmt)

    async def get_daily_closes(
        self,
        session: AsyncSession,
        *,
        symbols: list[str],
        since: datetime,
    ) -> dict[str, list[tuple[datetime, float]]]:
        """
        @bodhi.intent Read daily close prices for specified symbols over a time window
        @bodhi.reads klines(symbol, close, open_time) WHERE interval='1d' AND symbol IN (:symbols) AND open_time >= :since
        """
        stmt = (
            select(Kline.symbol, Kline.open_time, Kline.close)
            .where(
                Kline.interval == "1d",
                Kline.symbol.in_(symbols),
                Kline.open_time >= since,
            )
            .order_by(Kline.symbol, Kline.open_time)
        )
        result = await session.execute(stmt)
        rows = result.all()

        closes: dict[str, list[tuple[datetime, float]]] = {}
        for symbol, open_time, close in rows:
            closes.setdefault(symbol, []).append((open_time, float(close)))
        return closes
