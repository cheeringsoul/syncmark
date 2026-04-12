"""Redis Stream publisher for downstream alerts consumed by api-server."""
from __future__ import annotations

import json
from datetime import datetime
from typing import Any

import redis.asyncio as redis

from ..config import PublishConfig


def _flatten(payload: dict[str, Any]) -> dict[str, str]:
    out: dict[str, str] = {}
    for k, v in payload.items():
        if v is None:
            out[k] = ""
        elif isinstance(v, (dict, list)):
            out[k] = json.dumps(v, ensure_ascii=False, default=str)
        elif isinstance(v, datetime):
            out[k] = v.isoformat()
        else:
            out[k] = str(v)
    return out


class RedisPublisher:
    def __init__(self, client: redis.Redis, cfg: PublishConfig) -> None:
        self._redis = client
        self._cfg = cfg

    async def publish_news_analyzed(self, payload: dict[str, Any]) -> None:
        """
        @bodhi.intent Publish news_analyzed event for api-server to push to clients
        @bodhi.emits news_analyzed(news_id, title, ai_summary, sentiment, related_symbols, importance, analyzed_at) to redis:news:analyzed
        """
        await self._redis.xadd(self._cfg.news_analyzed, _flatten(payload))

    async def publish_economic_analyzed(self, payload: dict[str, Any]) -> None:
        """
        @bodhi.intent Publish economic_event_analyzed event for api-server to push
        @bodhi.emits economic_event_analyzed(event_id, name, country, actual, forecast, previous, ai_analysis, importance, published_at) to redis:economic:analyzed
        """
        await self._redis.xadd(self._cfg.economic_analyzed, _flatten(payload))

    async def publish_large_order_alert(self, payload: dict[str, Any]) -> None:
        """
        @bodhi.intent Publish enriched large_order_alert event
        @bodhi.emits large_order_alert(exchange, symbol, side, price, quantity, value_usd, severity, spot_price, deviation_pct, timestamp) to redis:alerts:large_orders
        """
        await self._redis.xadd(self._cfg.large_order_alert, _flatten(payload))

    async def publish_whale_alert(self, payload: dict[str, Any]) -> None:
        """
        @bodhi.intent Publish enriched whale_alert event
        @bodhi.emits whale_alert(chain, kind, tx_hash, from_address, from_label, to_address, to_label, token, amount, value_usd, severity, direction, timestamp) to redis:alerts:whales
        """
        await self._redis.xadd(self._cfg.whale_alert, _flatten(payload))
