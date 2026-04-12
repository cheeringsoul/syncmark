"""Reusable Redis Stream consumer loop with consumer group + DLQ."""
from __future__ import annotations

import asyncio
from typing import Awaitable, Callable

import redis.asyncio as redis
import structlog
from redis.exceptions import ResponseError

log = structlog.get_logger(__name__)

MAX_DELIVERY_ATTEMPTS = 3
BLOCK_MS = 5000

Handler = Callable[[dict[str, str]], Awaitable[None]]


async def ensure_group(client: redis.Redis, stream: str, group: str) -> None:
    """
    @bodhi.intent Idempotently create consumer group on a Redis Stream
    """
    try:
        await client.xgroup_create(name=stream, groupname=group, id="$", mkstream=True)
    except ResponseError as exc:
        if "BUSYGROUP" not in str(exc):
            raise


async def run_consumer_loop(
    *,
    client: redis.Redis,
    stream: str,
    group: str,
    consumer: str,
    handler: Handler,
    dlq_stream: str,
) -> None:
    """
    @bodhi.intent Long-running XREADGROUP loop — dispatch each message to handler, move poison messages to DLQ after MAX_DELIVERY_ATTEMPTS
    """
    await ensure_group(client, stream, group)
    log.info("consumer_started", stream=stream, group=group, consumer=consumer)
    while True:
        try:
            resp = await client.xreadgroup(
                groupname=group,
                consumername=consumer,
                streams={stream: ">"},
                count=16,
                block=BLOCK_MS,
            )
        except asyncio.CancelledError:
            log.info("consumer_cancelled", stream=stream)
            raise
        except Exception as exc:
            log.error("xreadgroup_failed", stream=stream, error=str(exc))
            await asyncio.sleep(1.0)
            continue

        if not resp:
            continue

        for _stream_name, messages in resp:
            for msg_id, fields in messages:
                await _process_one(
                    client=client,
                    stream=stream,
                    group=group,
                    msg_id=msg_id,
                    fields=fields,
                    handler=handler,
                    dlq_stream=dlq_stream,
                )


async def _process_one(
    *,
    client: redis.Redis,
    stream: str,
    group: str,
    msg_id: str,
    fields: dict[str, str],
    handler: Handler,
    dlq_stream: str,
) -> None:
    try:
        await handler(fields)
        await client.xack(stream, group, msg_id)
    except Exception as exc:
        log.error("handler_failed", stream=stream, msg_id=msg_id, error=str(exc))
        pending = await client.xpending_range(
            name=stream, groupname=group, min=msg_id, max=msg_id, count=1
        )
        delivery_count = pending[0]["times_delivered"] if pending else 1
        if delivery_count >= MAX_DELIVERY_ATTEMPTS:
            await client.xadd(
                dlq_stream,
                {
                    "source_stream": stream,
                    "msg_id": msg_id,
                    "error": str(exc),
                    **fields,
                },
            )
            await client.xack(stream, group, msg_id)
            log.warning("msg_to_dlq", stream=stream, msg_id=msg_id, attempts=delivery_count)
