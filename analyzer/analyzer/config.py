"""Configuration loading from YAML + environment."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

import yaml


@dataclass(frozen=True)
class DatabaseConfig:
    dsn: str
    pool_size: int
    max_overflow: int


@dataclass(frozen=True)
class RedisConfig:
    url: str
    consumer_id: str


@dataclass(frozen=True)
class LLMConfig:
    provider: str
    model: str
    api_key: str
    timeout_seconds: int
    max_retries: int


@dataclass(frozen=True)
class StreamsConfig:
    telegram_raw: str
    macro_events: str
    cex_large_orders: str
    chain_whales: str
    chain_smart_money: str
    dlq: str


@dataclass(frozen=True)
class PublishConfig:
    news_analyzed: str
    economic_analyzed: str
    large_order_alert: str
    whale_alert: str


@dataclass(frozen=True)
class ServerConfig:
    host: str
    port: int


@dataclass(frozen=True)
class Thresholds:
    large_order_high_usd: float
    large_order_extreme_usd: float
    whale_high_usd: float
    whale_extreme_usd: float
    llm_circuit_breaker_threshold: int
    llm_circuit_breaker_window_seconds: int


@dataclass(frozen=True)
class AppConfig:
    database: DatabaseConfig
    redis: RedisConfig
    llm: LLMConfig
    streams: StreamsConfig
    publish: PublishConfig
    server: ServerConfig
    thresholds: Thresholds


def load_config(path: str | os.PathLike[str] | None = None) -> AppConfig:
    cfg_path = Path(path or os.environ.get("ANALYZER_CONFIG", "configs/analyzer.yaml"))
    raw = yaml.safe_load(cfg_path.read_text())

    llm_raw = raw["llm"]
    api_key_env = llm_raw.get("api_key_env", "ANTHROPIC_API_KEY")
    api_key = os.environ.get(api_key_env, "")

    return AppConfig(
        database=DatabaseConfig(**raw["database"]),
        redis=RedisConfig(**raw["redis"]),
        llm=LLMConfig(
            provider=llm_raw["provider"],
            model=llm_raw["model"],
            api_key=api_key,
            timeout_seconds=llm_raw["timeout_seconds"],
            max_retries=llm_raw["max_retries"],
        ),
        streams=StreamsConfig(**raw["streams"]),
        publish=PublishConfig(**raw["publish"]),
        server=ServerConfig(**raw["server"]),
        thresholds=Thresholds(**raw["thresholds"]),
    )
