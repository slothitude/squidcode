"""Main entry point: starts ICAP + SSE servers concurrently."""

from __future__ import annotations

import asyncio

import structlog
import uvicorn

from squidcode.config import settings
from squidcode.icap.server import ICAPServer
from squidcode.sse.endpoint import create_sse_app
from squidcode.sse.manager import SSEManager

logger = structlog.get_logger("squidcode")

# Shared resources — initialized in run()
sse_manager: SSEManager
icap_server: ICAPServer


async def _rewrite_html(body: bytes) -> bytes | None:
    """Called by ICAP handler for text/html bodies.

    Parses HTML, injects runtime, returns modified HTML.
    Starts a background pipeline task for LLM rewriting.
    """
    from squidcode.rewriter.html_parser import parse_html
    from squidcode.rewriter.script_injector import inject_runtime
    from squidcode.utils.session import generate_session_id

    html = body.decode("utf-8", errors="replace")

    # Parse and tag text nodes
    page = parse_html(html)

    if not page.text_nodes:
        # No rewrable text — return original
        return None

    # Generate session and inject runtime
    session_id = generate_session_id()
    modified = inject_runtime(page.modified_html, session_id, settings.sse_origin)

    # Start background rewrite pipeline
    sse_manager.create_session(session_id)

    pipeline_task = _get_pipeline()
    if pipeline_task is not None:
        asyncio.create_task(
            pipeline_task.run(page.text_nodes, session_id),
            name=f"rewrite-{session_id}",
        )

    return modified.encode("utf-8")


def _get_pipeline():
    """Lazily import and return the rewrite pipeline (avoids circular imports)."""
    try:
        from squidcode.rewriter.pipeline import get_pipeline
        return get_pipeline()
    except Exception as e:
        logger.warn("main.pipeline_unavailable", error=str(e))
        return None


async def run():
    """Start both servers."""
    global sse_manager, icap_server

    logger.info(
        "main.starting",
        icap=f"{settings.icap_host}:{settings.icap_port}",
        sse=f"{settings.sse_host}:{settings.sse_port}",
    )

    # Initialize shared SSE manager
    sse_manager = SSEManager()

    # Initialize the rewrite pipeline (cache, RAG, LLM)
    try:
        from squidcode.rewriter.pipeline import init_pipeline
        init_pipeline(sse_manager)
        logger.info("main.pipeline_initialized")
    except Exception as e:
        logger.warn("main.pipeline_init_failed", error=str(e))

    # Start ICAP server
    icap_server = ICAPServer(
        host=settings.icap_host,
        port=settings.icap_port,
        rewrite_fn=_rewrite_html,
    )
    await icap_server.start()

    # Start SSE server (uvicorn in-process)
    app = create_sse_app(sse_manager)
    config = uvicorn.Config(
        app,
        host=settings.sse_host,
        port=settings.sse_port,
        log_level=settings.log_level.lower(),
    )
    sse_server = uvicorn.Server(config)

    # Run both concurrently
    await asyncio.gather(
        icap_server._server.serve_forever(),
        sse_server.serve(),
    )
