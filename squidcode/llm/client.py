"""Async streaming LLM client (OpenAI-compatible)."""

from __future__ import annotations

import re
from typing import AsyncGenerator

import structlog
from openai import AsyncOpenAI

from squidcode.config import settings
from squidcode.llm.prompts import build_system_prompt, build_user_prompt
from squidcode.rag.retriever import RAGContext

logger = structlog.get_logger("squidcode.llm")

# Pattern to detect completed sections: ---ID:sq-N--- followed by text until next ---ID: or end
_SENTINEL_RE = re.compile(r"---ID:(sq-\d+)---\s*\n?")
_SECTION_RE = re.compile(r"---ID:(sq-\d+)---\s*\n(.*?)(?=---ID:|$)", re.DOTALL)


class LLMClient:
    """Async streaming LLM client."""

    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
        model: str | None = None,
        temperature: float | None = None,
    ):
        self.client = AsyncOpenAI(
            api_key=api_key or settings.llm_api_key,
            base_url=base_url or settings.llm_base_url,
        )
        self.model = model or settings.llm_model
        self.temperature = temperature or settings.llm_temperature

    async def stream_rewrite(
        self,
        texts: list[str],
        ids: list[str],
        rag_context: RAGContext | None = None,
        style: str | None = None,
    ) -> AsyncGenerator[tuple[str, str], None]:
        """Stream rewrite of text batch. Yields (ai_id, rewritten_text) tuples.

        Uses sentinel delimiter parsing to detect completed sections.
        """
        system_prompt = build_system_prompt(
            style or settings.rewrite_style,
            rag_context,
        )
        user_prompt = build_user_prompt(texts, ids)

        try:
            stream = await self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=self.temperature,
                stream=True,
            )
        except Exception:
            logger.exception("llm.stream_error")
            return

        accumulated = ""
        completed_ids: set[str] = set()

        async for chunk in stream:
            delta = chunk.choices[0].delta
            if delta.content:
                accumulated += delta.content

                # Check for completed sections
                for match in _SECTION_RE.finditer(accumulated):
                    ai_id = match.group(1)
                    if ai_id not in completed_ids:
                        text = match.group(2).strip()
                        if text:
                            completed_ids.add(ai_id)
                            yield (ai_id, text)

        # Handle single-item batch (LLM may not use delimiters)
        if len(ids) == 1 and ids[0] not in completed_ids:
            text = _SENTINEL_RE.sub("", accumulated).strip()
            if text:
                yield (ids[0], text)

        # Log any missing IDs
        expected = set(ids)
        missing = expected - completed_ids
        if missing and len(ids) > 1:
            logger.warn("llm.missing_ids", missing=missing)

    async def rewrite_single(
        self,
        text: str,
        ai_id: str,
        rag_context: RAGContext | None = None,
    ) -> str | None:
        """Convenience: rewrite a single text node, return result or None."""
        async for rid, rtext in self.stream_rewrite(
            [text], [ai_id], rag_context
        ):
            return rtext
        return None
