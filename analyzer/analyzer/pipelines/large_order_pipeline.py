"""Large CEX order pipeline — rule-based enrichment, no LLM."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

import redis.asyncio as redis
import structlog

from ..config import Thresholds
from ..publisher.redis_publisher import RedisPublisher

log = structlog.get_logger(__name__)


def _coerce_float(value: str | None) -> float:
    if value in (None, ""):
        return 0.0
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


class LargeOrderPipeline:
    def __init__(
        self,
        *,
        redis_client: redis.Redis,
        publisher: RedisPublisher,
        thresholds: Thresholds,
    ) -> None:
        self._redis = redis_client
        self._publisher = publisher
        self._thresholds = thresholds

    async def handle(self, fields: dict[str, str]) -> None:
        """
        @bodhi.intent Enrich a CEX large order with spot price + severity, then publish alert
        @bodhi.reads redis:ticker:{exchange}:{symbol}(price)
        @bodhi.calls LargeOrderPipeline.classify_severity
        @bodhi.calls RedisPublisher.publish_large_order_alert
        @bodhi.on_fail missing_ticker → degrade(severity=unknown) → continue
        """
        exchange = fields.get("exchange", "")
        symbol = fields.get("symbol", "")
        price = _coerce_float(fields.get("price"))
        value_usd = _coerce_float(fields.get("value_usd"))

        spot_price = await self._read_spot_price(exchange, symbol)
        deviation_pct = 0.0
        if spot_price and price:
            deviation_pct = round((price - spot_price) / spot_price * 100.0, 4)

        severity = self.classify_severity(value_usd)

        await self._publisher.publish_large_order_alert(
            {
                "exchange": exchange,
                "symbol": symbol,
                "side": fields.get("side", ""),
                "price": price,
                "quantity": _coerce_float(fields.get("quantity")),
                "value_usd": value_usd,
                "severity": severity,
                "spot_price": spot_price or 0.0,
                "deviation_pct": deviation_pct,
                "timestamp": fields.get("timestamp") or datetime.now(timezone.utc).isoformat(),
            }
        )

    def classify_severity(self, value_usd: float) -> str:
        """
        @bodhi.intent Map USD value to severity bucket: low / medium / high / extreme
        """
        if value_usd >= self._thresholds.large_order_extreme_usd:
            return "extreme"
        if value_usd >= self._thresholds.large_order_high_usd:
            return "high"
        if value_usd >= self._thresholds.large_order_high_usd / 5:
            return "medium"
        return "low"

    async def _read_spot_price(self, exchange: str, symbol: str) -> Optional[float]:
        if not exchange or not symbol:
            return None
        key = f"ticker:{exchange}:{symbol}"
        try:
            raw = await self._redis.hget(key, "price")
        except Exception as exc:
            log.warning("ticker_read_failed", key=key, error=str(exc))
            return None
        if not raw:
            return None
        try:
            return float(raw)
        except ValueError:
            return None
