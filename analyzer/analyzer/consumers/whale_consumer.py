"""Whale + smart money consumer (multiplexed across two streams)."""
from __future__ import annotations

import asyncio

from ..pipelines.whale_pipeline import WhalePipeline
from .base import run_consumer_loop


class WhaleConsumer:
    """XREADGROUP loops on whale_transfers and smart_money streams → drives whale_pipeline."""

    def __init__(
        self,
        *,
        redis_client,
        whale_stream: str,
        smart_money_stream: str,
        whale_group: str,
        smart_money_group: str,
        consumer_id: str,
        dlq_stream: str,
        pipeline: WhalePipeline,
    ) -> None:
        self._redis = redis_client
        self._whale_stream = whale_stream
        self._smart_money_stream = smart_money_stream
        self._whale_group = whale_group
        self._smart_money_group = smart_money_group
        self._consumer_id = consumer_id
        self._dlq_stream = dlq_stream
        self._pipeline = pipeline

    async def run(self) -> None:
        """
        @bodhi.intent Run two parallel XREADGROUP loops on whale_transfers and smart_money streams
        @bodhi.consumes chain_whale_transfer(chain, tx_hash, from_address, from_label, to_address, to_label, token, amount, value_usd, timestamp) from redis:chain:whale_transfers
        @bodhi.consumes chain_smart_money(chain, address, label, action, token, amount, value_usd, tx_hash, timestamp) from redis:chain:smart_money
        @bodhi.calls WhalePipeline.handle_transfer
        @bodhi.calls WhalePipeline.handle_smart_money
        """
        await asyncio.gather(
            run_consumer_loop(
                client=self._redis,
                stream=self._whale_stream,
                group=self._whale_group,
                consumer=self._consumer_id,
                handler=self._pipeline.handle_transfer,
                dlq_stream=self._dlq_stream,
            ),
            run_consumer_loop(
                client=self._redis,
                stream=self._smart_money_stream,
                group=self._smart_money_group,
                consumer=self._consumer_id,
                handler=self._pipeline.handle_smart_money,
                dlq_stream=self._dlq_stream,
            ),
        )
