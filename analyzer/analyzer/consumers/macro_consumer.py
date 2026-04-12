"""Macro economic event consumer."""
from __future__ import annotations

from ..pipelines.economic_pipeline import EconomicPipeline
from .base import run_consumer_loop


class MacroConsumer:
    """XREADGROUP loop on macro events stream → drives economic_pipeline."""

    def __init__(
        self,
        *,
        redis_client,
        stream: str,
        group: str,
        consumer_id: str,
        dlq_stream: str,
        pipeline: EconomicPipeline,
    ) -> None:
        self._redis = redis_client
        self._stream = stream
        self._group = group
        self._consumer_id = consumer_id
        self._dlq_stream = dlq_stream
        self._pipeline = pipeline

    async def run(self) -> None:
        """
        @bodhi.intent XREADGROUP loop on macro events stream → dispatch each event to EconomicPipeline.handle
        @bodhi.consumes macro_economic_event(event_id, name, country, importance, scheduled_at, previous, forecast, actual, status) from redis:macro:economic_events
        @bodhi.calls EconomicPipeline.handle
        """
        await run_consumer_loop(
            client=self._redis,
            stream=self._stream,
            group=self._group,
            consumer=self._consumer_id,
            handler=self._pipeline.handle,
            dlq_stream=self._dlq_stream,
        )
