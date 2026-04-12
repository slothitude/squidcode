"""In-memory SSE session manager — maps session IDs to asyncio Queues."""

from __future__ import annotations

import asyncio
import json
from typing import Optional

import structlog

logger = structlog.get_logger("squidcode.sse")


class SSEManager:
    """Manages SSE sessions and their associated queues."""

    def __init__(self):
        self._sessions: dict[str, asyncio.Queue] = {}

    def create_session(self, session_id: str) -> asyncio.Queue:
        """Create a new session queue (or return existing)."""
        if session_id not in self._sessions:
            self._sessions[session_id] = asyncio.Queue()
            logger.debug("sse.session_created", session_id=session_id)
        return self._sessions[session_id]

    async def push_update(self, session_id: str, ai_id: str, new_text: str):
        """Push a rewrite update to the SSE queue for a session."""
        queue = self._sessions.get(session_id)
        if queue is None:
            logger.warn("sse.no_session", session_id=session_id)
            return

        payload = json.dumps({"id": ai_id, "text": new_text})
        await queue.put(payload)
        logger.debug("sse.pushed", session_id=session_id, ai_id=ai_id)

    def remove_session(self, session_id: str):
        """Remove a session (client disconnected)."""
        self._sessions.pop(session_id, None)
        logger.debug("sse.session_removed", session_id=session_id)

    def get_queue(self, session_id: str) -> Optional[asyncio.Queue]:
        return self._sessions.get(session_id)
