"""Rewrite pipeline: cache → RAG → LLM → quality → store → SSE.

Orchestrates the full async state graph for text rewriting.
"""

from __future__ import annotations

from typing import Optional

import structlog

from squidcode.cache.semantic_cache import SemanticCache
from squidcode.config import settings
from squidcode.llm.client import LLMClient
from squidcode.rag.retriever import Retriever, RAGContext
from squidcode.rewriter.html_parser import TextNode
from squidcode.rewriter.text_batcher import batch_nodes
from squidcode.sse.manager import SSEManager
from squidcode.utils.quality import check_quality

logger = structlog.get_logger("squidcode.pipeline")

# Module-level singleton
_pipeline: Optional[RewritePipeline] = None


class RewritePipeline:
    """Async pipeline for rewriting text nodes."""

    def __init__(
        self,
        cache: SemanticCache,
        rag_retriever: Retriever,
        llm: LLMClient,
        sse: SSEManager,
    ):
        self.cache = cache
        self.rag = rag_retriever
        self.llm = llm
        self.sse = sse

    async def run(self, text_nodes: list[TextNode], session_id: str):
        """Run the full pipeline for all text nodes in a session."""
        batches = batch_nodes(text_nodes, batch_size=settings.batch_size)

        logger.info(
            "pipeline.start",
            session_id=session_id,
            total_nodes=len(text_nodes),
            batches=len(batches),
        )

        for batch_idx, batch in enumerate(batches):
            logger.debug(
                "pipeline.batch",
                batch=batch_idx,
                nodes=len(batch),
                session_id=session_id,
            )

            for node in batch:
                try:
                    await self._process_node(node, session_id)
                except Exception:
                    logger.exception(
                        "pipeline.node_error",
                        ai_id=node.ai_id,
                        session_id=session_id,
                    )
                    # On error, keep original text

        logger.info("pipeline.complete", session_id=session_id)

    async def _process_node(self, node: TextNode, session_id: str):
        """Process a single text node through the pipeline."""
        # Step 1: Check semantic cache
        cached = await self.cache.lookup(node.original_text)
        if cached:
            logger.debug("pipeline.cache_hit", ai_id=node.ai_id)
            await self.sse.push_update(session_id, node.ai_id, cached)
            return

        # Step 2: RAG retrieval
        rag_context = await self.rag.retrieve(node.original_text)

        # Step 3: LLM rewrite (with retry on quality failure)
        rewritten = await self._rewrite_with_retry(node, rag_context)

        # Step 4: Store in cache
        if rewritten != node.original_text:
            await self.cache.store(node.original_text, rewritten)

        # Step 5: Push to SSE
        await self.sse.push_update(session_id, node.ai_id, rewritten)

    async def _rewrite_with_retry(
        self,
        node: TextNode,
        rag_context: RAGContext,
        max_retries: int = 1,
    ) -> str:
        """Attempt LLM rewrite with quality-check retry."""
        for attempt in range(max_retries + 1):
            result = await self.llm.rewrite_single(
                text=node.original_text,
                ai_id=node.ai_id,
                rag_context=rag_context,
            )

            if result is None:
                logger.warn("pipeline.llm_no_result", ai_id=node.ai_id, attempt=attempt)
                continue

            if check_quality(node.original_text, result):
                return result

            logger.warn(
                "pipeline.quality_fail",
                ai_id=node.ai_id,
                attempt=attempt,
            )

        # Fallback: return original text
        logger.warn("pipeline.fallback_original", ai_id=node.ai_id)
        return node.original_text


def init_pipeline(sse_manager: SSEManager) -> RewritePipeline:
    """Initialize the global pipeline singleton."""
    global _pipeline

    from squidcode.cache.embedding import EmbeddingModel
    from squidcode.cache.semantic_cache import SemanticCache
    from squidcode.llm.client import LLMClient
    from squidcode.rag.retriever import Retriever
    from squidcode.rag.store import RAGStore

    embedding_model = EmbeddingModel.get(settings.embedding_model)
    cache = SemanticCache(embedding_model)
    rag_store = RAGStore(embedding_model)
    rag_retriever = Retriever(rag_store, embedding_model=embedding_model)
    llm = LLMClient()

    _pipeline = RewritePipeline(
        cache=cache,
        rag_retriever=rag_retriever,
        llm=llm,
        sse=sse_manager,
    )

    return _pipeline


def get_pipeline() -> RewritePipeline:
    """Get the initialized pipeline. Raises if not initialized."""
    if _pipeline is None:
        raise RuntimeError("Pipeline not initialized. Call init_pipeline() first.")
    return _pipeline
