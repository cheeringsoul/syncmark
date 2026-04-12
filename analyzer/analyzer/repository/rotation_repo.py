"""Rotation signal persistence and lifecycle transitions."""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from typing import Optional

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from .models import (
    ROTATION_STATUS_ACTIVE,
    ROTATION_STATUS_DETECTED,
    ROTATION_STATUS_EXPIRED,
    RotationSignal,
)


class RotationRepo:
    async def create_signal(
        self,
        session: AsyncSession,
        *,
        symbol: str,
        signal_type: str,
        benchmark: str,
        rs_current: Decimal,
        rs_peak: Decimal,
        rs_delta: Decimal,
        coin_return_long: Decimal,
        coin_return_short: Decimal,
        benchmark_return_short: Decimal,
        volatility: Decimal,
        ai_summary: Optional[str] = None,
    ) -> int:
        """
        @bodhi.intent Create rotation signal in DETECTED status, return id
        @bodhi.writes rotation_signals(symbol, signal_type, benchmark, rs_current, rs_peak, rs_delta, coin_return_long, coin_return_short, benchmark_return_short, volatility, status=DETECTED, detected_at) via INSERT
        """
        row = RotationSignal(
            symbol=symbol,
            signal_type=signal_type,
            benchmark=benchmark,
            rs_current=rs_current,
            rs_peak=rs_peak,
            rs_delta=rs_delta,
            coin_return_long=coin_return_long,
            coin_return_short=coin_return_short,
            benchmark_return_short=benchmark_return_short,
            volatility=volatility,
            status=ROTATION_STATUS_DETECTED,
            ai_summary=ai_summary,
            detected_at=datetime.now(timezone.utc),
        )
        session.add(row)
        await session.flush()
        return row.id

    async def promote_to_active(self, session: AsyncSession, signal_id: int) -> None:
        """
        @bodhi.intent Transition signal from DETECTED to ACTIVE after confirmation
        @bodhi.writes rotation_signals(status=ACTIVE) via UPDATE WHERE id=:signal_id
        """
        await session.execute(
            update(RotationSignal)
            .where(RotationSignal.id == signal_id)
            .values(status=ROTATION_STATUS_ACTIVE)
        )

    async def expire_signal(self, session: AsyncSession, signal_id: int) -> None:
        """
        @bodhi.intent Mark signal as EXPIRED when conditions no longer met
        @bodhi.writes rotation_signals(status=EXPIRED, expired_at) via UPDATE WHERE id=:signal_id
        """
        await session.execute(
            update(RotationSignal)
            .where(RotationSignal.id == signal_id)
            .values(
                status=ROTATION_STATUS_EXPIRED,
                expired_at=datetime.now(timezone.utc),
            )
        )

    async def get_active_signals(
        self, session: AsyncSession
    ) -> list[RotationSignal]:
        """
        @bodhi.intent Fetch all non-expired signals (DETECTED + ACTIVE)
        @bodhi.reads rotation_signals(id, symbol, signal_type, rs_current, rs_peak, status) WHERE status IN (DETECTED, ACTIVE)
        """
        stmt = (
            select(RotationSignal)
            .where(
                RotationSignal.status.in_([
                    ROTATION_STATUS_DETECTED,
                    ROTATION_STATUS_ACTIVE,
                ])
            )
            .order_by(RotationSignal.detected_at.desc())
        )
        result = await session.execute(stmt)
        return list(result.scalars().all())

    async def has_recent_signal(
        self,
        session: AsyncSession,
        *,
        symbol: str,
        signal_type: str,
        since: datetime,
    ) -> bool:
        """
        @bodhi.intent Check if a similar signal was already emitted recently to avoid duplicates
        @bodhi.reads rotation_signals(id) WHERE symbol=:symbol AND signal_type=:signal_type AND detected_at >= :since
        """
        stmt = (
            select(RotationSignal.id)
            .where(
                RotationSignal.symbol == symbol,
                RotationSignal.signal_type == signal_type,
                RotationSignal.detected_at >= since,
            )
            .limit(1)
        )
        result = await session.execute(stmt)
        return result.scalar_one_or_none() is not None
