"""Rotation monitor pipeline — computes relative strength and detects rotation signals."""
from __future__ import annotations

import statistics
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Optional

import structlog
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ..config import RotationConfig
from ..db import session_scope
from ..publisher.redis_publisher import RedisPublisher
from ..repository.kline_repo import KlineRepo
from ..repository.rotation_repo import RotationRepo

log = structlog.get_logger(__name__)


@dataclass
class CoinRS:
    """Computed relative strength metrics for a single coin."""

    symbol: str
    rs_current: float
    rs_peak: float
    rs_delta: float
    coin_return_long: float
    coin_return_short: float
    benchmark_return_short: float
    volatility: float
    signal_type: Optional[str]


class RotationPipeline:
    def __init__(
        self,
        *,
        session_factory: async_sessionmaker[AsyncSession],
        publisher: RedisPublisher,
        kline_repo: KlineRepo,
        rotation_repo: RotationRepo,
        config: RotationConfig,
    ) -> None:
        self._session_factory = session_factory
        self._publisher = publisher
        self._kline_repo = kline_repo
        self._rotation_repo = rotation_repo
        self._cfg = config

    async def handle(self) -> None:
        """
        @bodhi.intent Orchestrate full rotation analysis cycle — compute RS for all monitored coins, detect signals, expire stale, publish alerts
        @bodhi.reads klines(symbol, close, open_time) WHERE interval='1d' AND open_time > now()-long_window
        @bodhi.reads config(rotation.symbols, rotation.benchmark, rotation.thresholds)
        @bodhi.calls KlineRepo.get_daily_closes
        @bodhi.calls RotationPipeline._compute_rs
        @bodhi.calls RotationPipeline._detect_signals
        @bodhi.calls RotationPipeline._expire_stale_signals
        """
        now = datetime.now(timezone.utc)
        since = now - timedelta(days=self._cfg.long_window_days + 7)
        all_symbols = [self._cfg.benchmark] + self._cfg.symbols

        async with session_scope(self._session_factory) as session:
            closes = await self._kline_repo.get_daily_closes(
                session, symbols=all_symbols, since=since
            )

        benchmark_closes = closes.get(self._cfg.benchmark, [])
        if len(benchmark_closes) < self._cfg.short_window_days:
            log.warning(
                "rotation_skip_insufficient_data",
                benchmark=self._cfg.benchmark,
                days=len(benchmark_closes),
            )
            return

        rs_results = self._compute_rs(closes, benchmark_closes)
        await self._detect_signals(rs_results)
        await self._expire_stale_signals(rs_results)

        log.info(
            "rotation_cycle_complete",
            coins_analyzed=len(rs_results),
            signals=[r.symbol for r in rs_results if r.signal_type],
        )

    def _compute_rs(
        self,
        closes: dict[str, list[tuple[datetime, float]]],
        benchmark_closes: list[tuple[datetime, float]],
    ) -> list[CoinRS]:
        """
        @bodhi.intent Calculate relative strength of each coin vs benchmark over long and short windows
        @bodhi.reads klines daily close data (in-memory from prior DB read)
        """
        bm_long = self._period_return(benchmark_closes, self._cfg.long_window_days)
        bm_short = self._period_return(benchmark_closes, self._cfg.short_window_days)

        results: list[CoinRS] = []
        for symbol in self._cfg.symbols:
            coin_closes = closes.get(symbol, [])
            if len(coin_closes) < self._cfg.short_window_days:
                continue

            coin_long = self._period_return(coin_closes, self._cfg.long_window_days)
            coin_short = self._period_return(coin_closes, self._cfg.short_window_days)
            coin_mid = self._period_return(coin_closes, self._cfg.short_window_days * 2)

            # RS = coin return / benchmark return (handle zero-division)
            rs_current = coin_short / bm_short if bm_short != 0 else 1.0
            rs_long = coin_long / bm_long if bm_long != 0 else 1.0
            rs_mid = coin_mid / (self._period_return(benchmark_closes, self._cfg.short_window_days * 2) or 1.0)

            # RS peak: max of sampled RS over the long window
            rs_peak = max(rs_long, rs_mid, rs_current)

            # RS delta: how RS changed from mid-period to now
            rs_delta = rs_current - rs_mid

            # Volatility: std of daily returns over the short window
            vol = self._compute_volatility(coin_closes, self._cfg.short_window_days)

            # Classify signal
            signal_type = self._classify_signal(
                rs_current=rs_current,
                rs_peak=rs_peak,
                rs_delta=rs_delta,
                coin_return_long=coin_long,
                benchmark_return_short=bm_short,
                volatility=vol,
            )

            results.append(
                CoinRS(
                    symbol=symbol,
                    rs_current=round(rs_current, 4),
                    rs_peak=round(rs_peak, 4),
                    rs_delta=round(rs_delta, 4),
                    coin_return_long=round(coin_long, 4),
                    coin_return_short=round(coin_short, 4),
                    benchmark_return_short=round(bm_short, 4),
                    volatility=round(vol, 4),
                    signal_type=signal_type,
                )
            )

        return results

    def _classify_signal(
        self,
        *,
        rs_current: float,
        rs_peak: float,
        rs_delta: float,
        coin_return_long: float,
        benchmark_return_short: float,
        volatility: float,
    ) -> Optional[str]:
        """
        @bodhi.intent Classify rotation signal type based on RS metrics and thresholds
        @bodhi.reads config(rotation.thresholds)
        """
        t = self._cfg.thresholds

        # Sell signal: was leading, now lagging while market is up
        if (
            rs_peak >= t.rs_leading
            and rs_current < t.rs_sell_signal
            and rs_delta < t.rs_delta_sell
            and benchmark_return_short >= t.benchmark_min_return
        ):
            return "sell_signal"

        # Weakening: was leading, RS dropping but not yet below 1.0
        if (
            rs_peak >= t.rs_leading
            and rs_current >= t.rs_sell_signal
            and rs_delta < t.rs_delta_sell * 0.5
        ):
            return "weakening"

        # Rising: RS climbing from below to above average
        if rs_delta > abs(t.rs_delta_sell) and rs_current > 1.2:
            return "rising"

        # Leading: RS well above baseline and still rising
        if rs_current >= t.rs_leading and rs_delta >= 0:
            return "leading"

        return None

    async def _detect_signals(self, rs_results: list[CoinRS]) -> None:
        """
        @bodhi.intent Check RS reversal conditions against thresholds, persist new signals, publish alerts
        @bodhi.writes rotation_signals(symbol, signal_type, rs_current, rs_peak, rs_delta, coin_return_long, coin_return_short, benchmark_return_short, volatility, status=DETECTED, detected_at) via INSERT
        @bodhi.emits rotation_alert(signal_id, symbol, signal_type, rs_current, rs_peak, rs_delta, coin_return_long, coin_return_short, benchmark_return_short, detected_at) to redis:alerts:rotation
        @bodhi.on_fail db_error → log + skip
        """
        # Only persist actionable signals
        actionable = [r for r in rs_results if r.signal_type in ("sell_signal", "weakening")]
        if not actionable:
            return

        dedup_since = datetime.now(timezone.utc) - timedelta(hours=24)

        async with session_scope(self._session_factory) as session:
            for coin_rs in actionable:
                # Skip if we already emitted this signal recently
                has_recent = await self._rotation_repo.has_recent_signal(
                    session,
                    symbol=coin_rs.symbol,
                    signal_type=coin_rs.signal_type,
                    since=dedup_since,
                )
                if has_recent:
                    log.debug("rotation_signal_dedup", symbol=coin_rs.symbol, type=coin_rs.signal_type)
                    continue

                try:
                    signal_id = await self._rotation_repo.create_signal(
                        session,
                        symbol=coin_rs.symbol,
                        signal_type=coin_rs.signal_type,
                        benchmark=self._cfg.benchmark,
                        rs_current=Decimal(str(coin_rs.rs_current)),
                        rs_peak=Decimal(str(coin_rs.rs_peak)),
                        rs_delta=Decimal(str(coin_rs.rs_delta)),
                        coin_return_long=Decimal(str(coin_rs.coin_return_long)),
                        coin_return_short=Decimal(str(coin_rs.coin_return_short)),
                        benchmark_return_short=Decimal(str(coin_rs.benchmark_return_short)),
                        volatility=Decimal(str(coin_rs.volatility)),
                    )

                    await self._publisher.publish_rotation_alert(
                        {
                            "signal_id": signal_id,
                            "symbol": coin_rs.symbol,
                            "signal_type": coin_rs.signal_type,
                            "rs_current": coin_rs.rs_current,
                            "rs_peak": coin_rs.rs_peak,
                            "rs_delta": coin_rs.rs_delta,
                            "coin_return_long": coin_rs.coin_return_long,
                            "coin_return_short": coin_rs.coin_return_short,
                            "benchmark_return_short": coin_rs.benchmark_return_short,
                            "volatility": coin_rs.volatility,
                            "detected_at": datetime.now(timezone.utc).isoformat(),
                        }
                    )

                    log.info(
                        "rotation_signal_created",
                        signal_id=signal_id,
                        symbol=coin_rs.symbol,
                        type=coin_rs.signal_type,
                        rs=coin_rs.rs_current,
                    )
                except Exception:
                    log.exception("rotation_signal_persist_failed", symbol=coin_rs.symbol)

    async def _expire_stale_signals(self, rs_results: list[CoinRS]) -> None:
        """
        @bodhi.intent Mark ACTIVE/DETECTED signals as EXPIRED when conditions no longer met
        @bodhi.reads rotation_signals(id, symbol, status) WHERE status IN (DETECTED, ACTIVE)
        @bodhi.writes rotation_signals(status=EXPIRED, expired_at) via UPDATE WHERE conditions_no_longer_met
        """
        # Build lookup of current signal types
        current_signals = {r.symbol: r.signal_type for r in rs_results}

        async with session_scope(self._session_factory) as session:
            active = await self._rotation_repo.get_active_signals(session)
            for sig in active:
                current_type = current_signals.get(sig.symbol)
                # Expire if the signal type no longer matches
                if current_type != sig.signal_type:
                    await self._rotation_repo.expire_signal(session, sig.id)
                    log.info(
                        "rotation_signal_expired",
                        signal_id=sig.id,
                        symbol=sig.symbol,
                        was=sig.signal_type,
                        now=current_type,
                    )

    @staticmethod
    def _period_return(
        closes: list[tuple[datetime, float]], days: int
    ) -> float:
        """
        @bodhi.intent Calculate percentage return over the last N days from close price series
        """
        if len(closes) < 2:
            return 0.0
        recent = closes[-min(days, len(closes)):]
        start_price = recent[0][1]
        end_price = recent[-1][1]
        if start_price == 0:
            return 0.0
        return ((end_price - start_price) / start_price) * 100.0

    @staticmethod
    def _compute_volatility(
        closes: list[tuple[datetime, float]], days: int
    ) -> float:
        """
        @bodhi.intent Calculate daily return volatility (stdev of pct changes) over recent N days
        """
        recent = closes[-min(days + 1, len(closes)):]
        if len(recent) < 3:
            return 0.0
        daily_returns = []
        for i in range(1, len(recent)):
            prev = recent[i - 1][1]
            if prev == 0:
                continue
            daily_returns.append((recent[i][1] - prev) / prev * 100.0)
        if len(daily_returns) < 2:
            return 0.0
        return statistics.stdev(daily_returns)
