"""Periodic scheduler for rotation analysis — runs every N hours."""
from __future__ import annotations

import asyncio

import structlog

from ..config import RotationConfig
from ..pipelines.rotation_pipeline import RotationPipeline

log = structlog.get_logger(__name__)


class RotationScheduler:
    """Periodic trigger for RotationPipeline.handle — not a stream consumer."""

    def __init__(
        self,
        *,
        pipeline: RotationPipeline,
        config: RotationConfig,
    ) -> None:
        self._pipeline = pipeline
        self._cfg = config

    async def run(self) -> None:
        """
        @bodhi.intent Trigger rotation pipeline on periodic schedule, sleep between cycles
        @bodhi.reads config(rotation.interval_hours, rotation.enabled)
        @bodhi.calls RotationPipeline.handle
        """
        interval_seconds = self._cfg.interval_hours * 3600
        log.info(
            "rotation_scheduler_started",
            interval_hours=self._cfg.interval_hours,
            symbols=len(self._cfg.symbols),
            benchmark=self._cfg.benchmark,
        )

        while True:
            try:
                log.info("rotation_cycle_start")
                await self._pipeline.handle()
            except asyncio.CancelledError:
                log.info("rotation_scheduler_cancelled")
                raise
            except Exception:
                log.exception("rotation_cycle_failed")

            await asyncio.sleep(interval_seconds)
