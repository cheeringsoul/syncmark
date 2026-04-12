"""Whale + smart-money pipeline — rule-based classification."""
from __future__ import annotations

from datetime import datetime, timezone

import structlog

from ..config import Thresholds
from ..publisher.redis_publisher import RedisPublisher

log = structlog.get_logger(__name__)

_CEX_KEYWORDS = ("binance", "okx", "coinbase", "bybit", "kraken", "huobi", "bitfinex")


def _coerce_float(value: str | None) -> float:
    if value in (None, ""):
        return 0.0
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _is_cex_label(label: str | None) -> bool:
    if not label:
        return False
    lowered = label.lower()
    return any(k in lowered for k in _CEX_KEYWORDS)


class WhalePipeline:
    def __init__(self, *, publisher: RedisPublisher, thresholds: Thresholds) -> None:
        self._publisher = publisher
        self._thresholds = thresholds

    async def handle_transfer(self, fields: dict[str, str]) -> None:
        """
        @bodhi.intent Classify a labeled whale transfer (cex_inflow / cex_outflow / wallet_to_wallet) and publish alert
        @bodhi.calls WhalePipeline.classify
        @bodhi.calls RedisPublisher.publish_whale_alert
        """
        value_usd = _coerce_float(fields.get("value_usd"))
        from_label = fields.get("from_label") or ""
        to_label = fields.get("to_label") or ""
        severity, direction = self.classify(value_usd=value_usd, from_label=from_label, to_label=to_label)

        await self._publisher.publish_whale_alert(
            {
                "chain": fields.get("chain", ""),
                "kind": "whale_transfer",
                "tx_hash": fields.get("tx_hash", ""),
                "from_address": fields.get("from_address", ""),
                "from_label": from_label,
                "to_address": fields.get("to_address", ""),
                "to_label": to_label,
                "token": fields.get("token", ""),
                "amount": _coerce_float(fields.get("amount")),
                "value_usd": value_usd,
                "severity": severity,
                "direction": direction,
                "timestamp": fields.get("timestamp") or datetime.now(timezone.utc).isoformat(),
            }
        )

    async def handle_smart_money(self, fields: dict[str, str]) -> None:
        """
        @bodhi.intent Translate a smart money buy/sell into the unified whale_alert format
        @bodhi.calls RedisPublisher.publish_whale_alert
        """
        value_usd = _coerce_float(fields.get("value_usd"))
        action = (fields.get("action") or "").lower()
        direction = "smart_money_buy" if action == "buy" else "smart_money_sell"
        severity, _ = self.classify(value_usd=value_usd, from_label="", to_label="")

        await self._publisher.publish_whale_alert(
            {
                "chain": fields.get("chain", ""),
                "kind": "smart_money",
                "tx_hash": fields.get("tx_hash", ""),
                "from_address": fields.get("address", "") if action == "sell" else "",
                "from_label": fields.get("label", "") if action == "sell" else "",
                "to_address": fields.get("address", "") if action == "buy" else "",
                "to_label": fields.get("label", "") if action == "buy" else "",
                "token": fields.get("token", ""),
                "amount": _coerce_float(fields.get("amount")),
                "value_usd": value_usd,
                "severity": severity,
                "direction": direction,
                "timestamp": fields.get("timestamp") or datetime.now(timezone.utc).isoformat(),
            }
        )

    def classify(self, *, value_usd: float, from_label: str, to_label: str) -> tuple[str, str]:
        """
        @bodhi.intent Pure function — derive (severity, direction) from value and address labels
        """
        if value_usd >= self._thresholds.whale_extreme_usd:
            severity = "extreme"
        elif value_usd >= self._thresholds.whale_high_usd:
            severity = "high"
        else:
            severity = "medium"

        if _is_cex_label(to_label) and not _is_cex_label(from_label):
            direction = "cex_inflow"
        elif _is_cex_label(from_label) and not _is_cex_label(to_label):
            direction = "cex_outflow"
        else:
            direction = "wallet_to_wallet"
        return severity, direction
