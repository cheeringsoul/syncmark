"""LLM prompt templates — string builders, no I/O."""
from __future__ import annotations

NEWS_SYSTEM = (
    "You are a crypto news analyst. Output strict JSON with keys: "
    "summary (<= 100 chars Chinese), sentiment (bullish|bearish|neutral), "
    "related_symbols (array of upper-case ticker strings), "
    "importance (high|medium|low). No prose outside JSON."
)

MACRO_SYSTEM = (
    "You are a macro economist focused on crypto markets. Given an economic "
    "indicator with previous/forecast/actual values, output one paragraph "
    "(<= 200 chars Chinese) describing the impact on crypto. Plain text only."
)

QA_SYSTEM = (
    "You are SyncMark's crypto market assistant. Answer the user's question "
    "in Chinese, <= 500 chars, grounded in the provided context. If the "
    "context is insufficient, say so explicitly."
)


def build_news_user_prompt(text: str, channel_name: str) -> str:
    return f"频道: {channel_name}\n消息内容:\n{text}\n\n请输出 JSON。"


def build_macro_user_prompt(
    name: str,
    country: str,
    previous: str | None,
    forecast: str | None,
    actual: str | None,
) -> str:
    return (
        f"指标: {name} ({country})\n"
        f"前值: {previous or '-'}\n"
        f"预期: {forecast or '-'}\n"
        f"实际: {actual or '-'}\n\n"
        "请用一段话分析对加密市场的影响。"
    )


def build_qa_user_prompt(question: str, context_blocks: list[str]) -> str:
    context = "\n\n".join(context_blocks) if context_blocks else "(no context)"
    return f"上下文:\n{context}\n\n用户提问:\n{question}"
