"""CEX large order consumer."""
from __future__ import annotations

from ..pipelines.large_order_pipeline import LargeOrderPipeline
from .base import run_consumer_loop


class LargeOrderConsumer:
    """XREADGROUP loop on cex large orders stream → drives large_order_pipeline."""

    def __init__(
        self,
        *,
        redis_client,
        stream: str,
        group: str,
        consumer_id: str,
        dlq_stream: str,
        pipeline: LargeOrderPipeline,
    ) -> None:
        self._redis = redis_client
        self._stream = stream
        self._group = group
        self._consumer_id = consumer_id
        self._dlq_stream = dlq_stream
        self._pipeline = pipeline

    async def run(self) -> None:
        """
        @bodhi.intent XREADGROUP loop on cex large orders stream → dispatch each order to LargeOrderPipeline.handle
        @bodhi.consumes cex_large_order(exchange, symbol, side, price, quantity, value_usd, timestamp) from redis:cex:large_orders
        @bodhi.calls LargeOrderPipeline.handle
        """
        await run_consumer_loop(
            client=self._redis,
            stream=self._stream,
            group=self._group,
            consumer=self._consumer_id,
            handler=self._pipeline.handle,
            dlq_stream=self._dlq_stream,
        )
