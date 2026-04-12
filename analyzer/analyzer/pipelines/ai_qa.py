"""Synchronous AI Q&A pipeline."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import structlog
from sqlalchemy.ext.asyncio import async_sessionmaker

from ..context.aggregator import ContextAggregator
from ..db import session_scope
from ..llm.client import LLMClient
from ..repository.ai_analysis_repo import AiAnalysisRepo

log = structlog.get_logger(__name__)


@dataclass(frozen=True)
class QaResult:
    answer: str
    sources: list[str]
    model: str
    latency_ms: int


class AiQaPipeline:
    def __init__(
        self,
        *,
        session_factory: async_sessionmaker,
        llm: LLMClient,
        aggregator: ContextAggregator,
        ai_analysis_repo: AiAnalysisRepo,
    ) -> None:
        self._session_factory = session_factory
        self._llm = llm
        self._aggregator = aggregator
        self._ai_analysis_repo = ai_analysis_repo

    async def run(self, *, question: str, user_id: Optional[str]) -> QaResult:
        """
        @bodhi.intent Aggregate context, call LLM, persist analysis row, return answer
        @bodhi.calls ContextAggregator.collect
        @bodhi.calls LLMClient.qa
        @bodhi.calls AiAnalysisRepo.record
        @bodhi.on_fail llm_timeout → reject 503
        @bodhi.on_fail llm_rate_limited → reject 429
        @bodhi.on_fail context_failure → reject 500
        """
        context_blocks = await self._aggregator.collect()
        llm_resp = await self._llm.qa(question=question, context_blocks=context_blocks)

        async with session_scope(self._session_factory) as session:
            await self._ai_analysis_repo.record(
                session,
                ref_type="question",
                ref_id=None,
                prompt=question,
                response=llm_resp.text,
                model=llm_resp.model,
                tokens_used=llm_resp.tokens_used,
                latency_ms=llm_resp.latency_ms,
            )

        return QaResult(
            answer=llm_resp.text.strip(),
            sources=[block.splitlines()[0] for block in context_blocks if block],
            model=llm_resp.model,
            latency_ms=llm_resp.latency_ms,
        )
