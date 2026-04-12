"""Analyzer service entry point — wires consumers + FastAPI together."""
from __future__ import annotations

import asyncio
import contextlib
import logging
import signal

import structlog
import uvicorn
from fastapi import FastAPI

from .api.routes import AskController, build_router
from .config import AppConfig, load_config
from .consumers.large_order_consumer import LargeOrderConsumer
from .consumers.macro_consumer import MacroConsumer
from .consumers.telegram_consumer import TelegramConsumer
from .consumers.whale_consumer import WhaleConsumer
from .context.aggregator import ContextAggregator
from .db import build_engine, build_session_maker
from .llm.client import LLMClient
from .pipelines.ai_qa import AiQaPipeline
from .pipelines.economic_pipeline import EconomicPipeline
from .pipelines.large_order_pipeline import LargeOrderPipeline
from .pipelines.news_pipeline import NewsPipeline
from .pipelines.whale_pipeline import WhalePipeline
from .publisher.redis_publisher import RedisPublisher
from .redis_client import build_redis
from .repository.ai_analysis_repo import AiAnalysisRepo
from .repository.economic_repo import EconomicRepo
from .repository.news_query import NewsQuery
from .repository.news_repo import NewsRepo
from .repository.telegram_repo import TelegramRepo

logging.basicConfig(level=logging.INFO)
structlog.configure(
    processors=[
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso", key="ts"),
        structlog.processors.JSONRenderer(),
    ]
)
log = structlog.get_logger(__name__)


def build_app(cfg: AppConfig) -> tuple[FastAPI, list[asyncio.Task]]:
    redis_client = build_redis(cfg.redis)
    engine = build_engine(cfg.database)
    session_factory = build_session_maker(engine)
    llm = LLMClient(cfg.llm, cfg.thresholds)
    publisher = RedisPublisher(redis_client, cfg.publish)

    telegram_repo = TelegramRepo()
    news_repo = NewsRepo()
    economic_repo = EconomicRepo()
    ai_analysis_repo = AiAnalysisRepo()
    news_query = NewsQuery()

    aggregator = ContextAggregator(
        session_factory=session_factory,
        redis_client=redis_client,
        news_query=news_query,
        economic_repo=economic_repo,
    )

    news_pipeline = NewsPipeline(
        session_factory=session_factory,
        llm=llm,
        publisher=publisher,
        telegram_repo=telegram_repo,
        news_repo=news_repo,
        ai_analysis_repo=ai_analysis_repo,
    )
    economic_pipeline = EconomicPipeline(
        session_factory=session_factory,
        llm=llm,
        publisher=publisher,
        economic_repo=economic_repo,
        ai_analysis_repo=ai_analysis_repo,
    )
    large_order_pipeline = LargeOrderPipeline(
        redis_client=redis_client, publisher=publisher, thresholds=cfg.thresholds
    )
    whale_pipeline = WhalePipeline(publisher=publisher, thresholds=cfg.thresholds)
    qa_pipeline = AiQaPipeline(
        session_factory=session_factory,
        llm=llm,
        aggregator=aggregator,
        ai_analysis_repo=ai_analysis_repo,
    )
    ask_controller = AskController(qa_pipeline)

    telegram_consumer = TelegramConsumer(
        redis_client=redis_client,
        stream=cfg.streams.telegram_raw,
        group="analyzer-news",
        consumer_id=cfg.redis.consumer_id,
        dlq_stream=cfg.streams.dlq,
        pipeline=news_pipeline,
    )
    macro_consumer = MacroConsumer(
        redis_client=redis_client,
        stream=cfg.streams.macro_events,
        group="analyzer-macro",
        consumer_id=cfg.redis.consumer_id,
        dlq_stream=cfg.streams.dlq,
        pipeline=economic_pipeline,
    )
    large_order_consumer = LargeOrderConsumer(
        redis_client=redis_client,
        stream=cfg.streams.cex_large_orders,
        group="analyzer-large-order",
        consumer_id=cfg.redis.consumer_id,
        dlq_stream=cfg.streams.dlq,
        pipeline=large_order_pipeline,
    )
    whale_consumer = WhaleConsumer(
        redis_client=redis_client,
        whale_stream=cfg.streams.chain_whales,
        smart_money_stream=cfg.streams.chain_smart_money,
        whale_group="analyzer-whale",
        smart_money_group="analyzer-smart-money",
        consumer_id=cfg.redis.consumer_id,
        dlq_stream=cfg.streams.dlq,
        pipeline=whale_pipeline,
    )

    app = FastAPI(title="syncmark-analyzer")
    app.include_router(build_router(ask_controller))

    consumer_tasks: list[asyncio.Task] = []

    @app.on_event("startup")
    async def _startup() -> None:
        log.info("analyzer_starting")
        consumer_tasks.append(asyncio.create_task(telegram_consumer.run(), name="telegram"))
        consumer_tasks.append(asyncio.create_task(macro_consumer.run(), name="macro"))
        consumer_tasks.append(asyncio.create_task(large_order_consumer.run(), name="large_order"))
        consumer_tasks.append(asyncio.create_task(whale_consumer.run(), name="whale"))

    @app.on_event("shutdown")
    async def _shutdown() -> None:
        log.info("analyzer_stopping")
        for task in consumer_tasks:
            task.cancel()
        for task in consumer_tasks:
            with contextlib.suppress(asyncio.CancelledError):
                await task
        await redis_client.aclose()
        await engine.dispose()

    return app, consumer_tasks


def cli() -> None:
    cfg = load_config()
    app, _ = build_app(cfg)

    server = uvicorn.Server(
        uvicorn.Config(
            app,
            host=cfg.server.host,
            port=cfg.server.port,
            log_level="info",
            lifespan="on",
        )
    )

    loop = asyncio.new_event_loop()

    def _stop(*_: object) -> None:
        loop.create_task(server.shutdown())

    for sig in (signal.SIGINT, signal.SIGTERM):
        with contextlib.suppress(NotImplementedError):
            loop.add_signal_handler(sig, _stop)

    loop.run_until_complete(server.serve())


if __name__ == "__main__":
    cli()
