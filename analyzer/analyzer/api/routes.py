"""FastAPI routes — synchronous AI Q&A endpoint exposed to api-server."""
from __future__ import annotations

import structlog
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from ..llm.client import CircuitBreakerOpen
from ..pipelines.ai_qa import AiQaPipeline

log = structlog.get_logger(__name__)


class AskRequest(BaseModel):
    question: str = Field(min_length=1, max_length=2000)
    user_id: str | None = None


class AskResponse(BaseModel):
    answer: str
    sources: list[str]
    model: str
    latency_ms: int


class AskController:
    def __init__(self, pipeline: AiQaPipeline) -> None:
        self._pipeline = pipeline

    async def ask(self, req: AskRequest) -> AskResponse:
        """
        @bodhi.intent HTTP entry — receive question, run AI Q&A pipeline, return answer
        @bodhi.reads request.body(question, user_id)
        @bodhi.calls AiQaPipeline.run
        @bodhi.writes response(200, answer, sources, model, latency_ms)
        @bodhi.on_fail circuit_breaker_open → reject 429
        @bodhi.on_fail llm_failure → reject 503
        """
        try:
            result = await self._pipeline.run(question=req.question, user_id=req.user_id)
        except CircuitBreakerOpen:
            raise HTTPException(status_code=429, detail="LLM rate limited, try again later")
        except Exception as exc:
            log.exception("ai_qa_failed", error=str(exc))
            raise HTTPException(status_code=503, detail="AI service unavailable")
        return AskResponse(
            answer=result.answer,
            sources=result.sources,
            model=result.model,
            latency_ms=result.latency_ms,
        )


def build_router(controller: AskController) -> APIRouter:
    router = APIRouter()

    @router.get("/healthz")
    async def healthz() -> dict[str, str]:
        return {"status": "ok"}

    router.add_api_route(
        "/analyze/ask",
        controller.ask,
        methods=["POST"],
        response_model=AskResponse,
    )
    return router
