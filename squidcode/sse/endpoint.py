"""FastAPI SSE endpoint."""

from __future__ import annotations

import asyncio
from typing import Optional

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse

from squidcode.sse.manager import SSEManager


def create_sse_app(sse_manager: SSEManager) -> FastAPI:
    app = FastAPI(title="SquidCode SSE", docs_url=None, redoc_url=None)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["GET"],
        allow_headers=["*"],
    )

    @app.get("/squidcode/sse/{session_id}")
    async def sse_endpoint(session_id: str, request: Request):
        """SSE endpoint for streaming rewrite updates to the browser."""
        queue = sse_manager.create_session(session_id)

        async def event_generator():
            try:
                while True:
                    # Check if client disconnected
                    if await request.is_disconnected():
                        break

                    try:
                        payload = await asyncio.wait_for(queue.get(), timeout=30)
                    except asyncio.TimeoutError:
                        # Send keepalive comment
                        yield ": keepalive\n\n"
                        continue

                    yield f"data: {payload}\n\n"
            finally:
                sse_manager.remove_session(session_id)

        return StreamingResponse(
            event_generator(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )

    @app.get("/squidcode/health")
    async def health():
        return {"status": "ok"}

    return app
