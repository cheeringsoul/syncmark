"""Anthropic Claude client wrapper with retry + simple circuit breaker."""
from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass
from typing import Optional

import structlog
from anthropic import APIError, APIStatusError, APITimeoutError, AsyncAnthropic

from ..config import LLMConfig, Thresholds
from . import prompts

log = structlog.get_logger(__name__)


@dataclass(frozen=True)
class LLMResponse:
    text: str
    model: str
    tokens_used: Optional[int]
    latency_ms: int


@dataclass(frozen=True)
class NewsAnalysis:
    summary: str
    sentiment: str
    related_symbols: list[str]
    importance: str


class CircuitBreakerOpen(Exception):
    pass


class _CircuitBreaker:
    def __init__(self, threshold: int, window_seconds: int) -> None:
        self._threshold = threshold
        self._window = window_seconds
        self._failures: list[float] = []
        self._opened_at: Optional[float] = None

    def record_success(self) -> None:
        self._failures.clear()
        self._opened_at = None

    def record_failure(self) -> None:
        now = time.monotonic()
        self._failures.append(now)
        self._failures = [t for t in self._failures if now - t <= self._window]
        if len(self._failures) >= self._threshold:
            self._opened_at = now

    def check(self) -> None:
        if self._opened_at is None:
            return
        if time.monotonic() - self._opened_at > self._window:
            self._opened_at = None
            self._failures.clear()
            return
        raise CircuitBreakerOpen("LLM circuit breaker open")


class LLMClient:
    def __init__(self, cfg: LLMConfig, thresholds: Thresholds) -> None:
        self._cfg = cfg
        self._client = AsyncAnthropic(api_key=cfg.api_key, timeout=cfg.timeout_seconds)
        self._breaker = _CircuitBreaker(
            thresholds.llm_circuit_breaker_threshold,
            thresholds.llm_circuit_breaker_window_seconds,
        )

    async def _call(self, system: str, user: str, max_tokens: int) -> LLMResponse:
        """
        @bodhi.intent Low-level Claude messages.create call with retry + breaker
        @bodhi.calls Anthropic.messages_create via http:POST https://api.anthropic.com/v1/messages
        @bodhi.on_fail llm_timeout → retry 2 → circuit_breaker(threshold=10, window=60s)
        """
        self._breaker.check()
        last_err: Exception | None = None
        start = time.monotonic()
        for attempt in range(self._cfg.max_retries + 1):
            try:
                resp = await self._client.messages.create(
                    model=self._cfg.model,
                    max_tokens=max_tokens,
                    system=system,
                    messages=[{"role": "user", "content": user}],
                )
                elapsed_ms = int((time.monotonic() - start) * 1000)
                text = "".join(
                    block.text for block in resp.content if getattr(block, "type", "") == "text"
                )
                tokens = (resp.usage.input_tokens + resp.usage.output_tokens) if resp.usage else None
                self._breaker.record_success()
                return LLMResponse(
                    text=text, model=self._cfg.model, tokens_used=tokens, latency_ms=elapsed_ms
                )
            except (APITimeoutError, APIStatusError, APIError) as exc:
                last_err = exc
                log.warning("llm_call_failed", attempt=attempt, error=str(exc))
                if attempt < self._cfg.max_retries:
                    await asyncio.sleep(0.5 * (attempt + 1))
                    continue
                self._breaker.record_failure()
                raise
        assert last_err is not None
        raise last_err

    async def analyze_news(self, *, text: str, channel_name: str) -> tuple[NewsAnalysis, LLMResponse]:
        """
        @bodhi.intent Call Claude to extract summary, sentiment, related symbols and importance from a news message
        @bodhi.calls LLMClient._call
        @bodhi.on_fail llm_invalid_json → degrade(rule_based_summary)
        """
        user = prompts.build_news_user_prompt(text, channel_name)
        resp = await self._call(prompts.NEWS_SYSTEM, user, max_tokens=400)
        analysis = _parse_news_json(resp.text)
        return analysis, resp

    async def analyze_macro(self, *, name: str, country: str, previous: Optional[str], forecast: Optional[str], actual: Optional[str]) -> LLMResponse:
        """
        @bodhi.intent Call Claude to produce an impact analysis for a published macro indicator
        @bodhi.calls LLMClient._call
        """
        user = prompts.build_macro_user_prompt(name, country, previous, forecast, actual)
        return await self._call(prompts.MACRO_SYSTEM, user, max_tokens=400)

    async def qa(self, *, question: str, context_blocks: list[str]) -> LLMResponse:
        """
        @bodhi.intent Synchronous Q&A — call Claude with question + aggregated context
        @bodhi.calls LLMClient._call
        @bodhi.on_fail llm_rate_limited → reject 429
        """
        user = prompts.build_qa_user_prompt(question, context_blocks)
        return await self._call(QA_SYSTEM_LOCAL, user, max_tokens=800)


QA_SYSTEM_LOCAL = prompts.QA_SYSTEM


def _parse_news_json(text: str) -> NewsAnalysis:
    raw = text.strip()
    if raw.startswith("```"):
        raw = raw.strip("`")
        if raw.lower().startswith("json"):
            raw = raw[4:].lstrip()
    data = json.loads(raw)
    return NewsAnalysis(
        summary=str(data.get("summary", "")).strip(),
        sentiment=str(data.get("sentiment", "neutral")).strip().lower(),
        related_symbols=[str(s).upper() for s in (data.get("related_symbols") or [])],
        importance=str(data.get("importance", "low")).strip().lower(),
    )


def rule_based_news_summary(text: str) -> NewsAnalysis:
    """
    @bodhi.intent Degraded fallback when LLM fails — truncate text and apply trivial sentiment heuristics
    """
    snippet = (text or "").strip().replace("\n", " ")
    if len(snippet) > 100:
        snippet = snippet[:97] + "..."
    lower = (text or "").lower()
    bullish_words = ("buy", "bullish", "up", "surge", "rally", "涨", "看涨", "利好")
    bearish_words = ("sell", "bearish", "down", "dump", "crash", "跌", "看跌", "利空")
    sentiment = "neutral"
    if any(w in lower for w in bullish_words):
        sentiment = "bullish"
    elif any(w in lower for w in bearish_words):
        sentiment = "bearish"
    return NewsAnalysis(
        summary=snippet or "(empty)",
        sentiment=sentiment,
        related_symbols=[],
        importance="low",
    )
