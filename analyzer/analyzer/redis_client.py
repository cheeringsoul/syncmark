"""Redis async client factory."""
from __future__ import annotations

import redis.asyncio as redis

from .config import RedisConfig


def build_redis(cfg: RedisConfig) -> redis.Redis:
    return redis.from_url(cfg.url, decode_responses=True)
