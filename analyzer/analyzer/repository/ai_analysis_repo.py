"""AI analyses audit-trail persistence."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession

from .models import AiAnalysis


class AiAnalysisRepo:
    async def record(self, session: AsyncSession, *, ref_type: str, ref_id: Optional[int], prompt: str, response: str, model: str, tokens_used: Optional[int], latency_ms: int) -> int:
        """
        @bodhi.intent Persist LLM call audit trail (prompt, response, tokens, latency)
        @bodhi.writes ai_analyses(ref_type, ref_id, prompt, response, model, tokens_used, latency_ms, created_at) via INSERT
        """
        row = AiAnalysis(
            ref_type=ref_type,
            ref_id=ref_id,
            prompt=prompt,
            response=response,
            model=model,
            tokens_used=tokens_used,
            latency_ms=latency_ms,
            created_at=datetime.now(timezone.utc),
        )
        session.add(row)
        await session.flush()
        return row.id
