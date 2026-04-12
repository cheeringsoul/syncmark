"""Telegram raw message consumer — entry point of the news pipeline."""
from __future__ import annotations

import structlog

from ..pipelines.news_pipeline import NewsPipeline
from .base import run_consumer_loop

log = structlog.get_logger(__name__)


class TelegramConsumer:
    """XREADGROUP loop on telegram raw message stream → drives news_pipeline."""

    def __init__(
        self,
        *,
        redis_client,
        stream: str,
        group: str,
        consumer_id: str,
        dlq_stream: str,
        pipeline: NewsPipeline,
    ) -> None:
        self._redis = redis_client
        self._stream = stream
        self._group = group
        self._consumer_id = consumer_id
        self._dlq_stream = dlq_stream
        self._pipeline = pipeline

    async def run(self) -> None:
        """
        @bodhi.intent XREADGROUP loop on telegram raw message stream → dispatch each message to NewsPipeline.handle
        @bodhi.consumes telegram_raw_message(channel_id, channel_name, message_id, text, media_type, media_url, telegram_date) from redis:telegram:raw_messages
        @bodhi.calls NewsPipeline.handle
        """
        await run_consumer_loop(
            client=self._redis,
            stream=self._stream,
            group=self._group,
            consumer=self._consumer_id,
            handler=self._pipeline.handle,
            dlq_stream=self._dlq_stream,
        )
