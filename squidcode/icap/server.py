"""Asyncio TCP server for ICAP protocol."""

from __future__ import annotations

import asyncio
from typing import Callable, Optional

import structlog

from squidcode.icap.handler import handle_request
from squidcode.icap.protocol import ICAPParser

logger = structlog.get_logger("squidcode.icap")


class ICAPServer:
    """Lightweight asyncio ICAP server."""

    def __init__(
        self,
        host: str = "0.0.0.0",
        port: int = 1344,
        rewrite_fn: Optional[Callable] = None,
    ):
        self.host = host
        self.port = port
        self.rewrite_fn = rewrite_fn
        self._server: Optional[asyncio.Server] = None

    async def start(self):
        self._server = await asyncio.start_server(
            self._handle_connection,
            self.host,
            self.port,
        )
        logger.info("icap.listening", host=self.host, port=self.port)

    async def serve(self):
        """Start and serve forever."""
        await self.start()
        async with self._server:
            await self._server.serve_forever()

    async def stop(self):
        if self._server:
            self._server.close()
            await self._server.wait_closed()
            logger.info("icap.stopped")

    async def _handle_connection(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
    ):
        addr = writer.get_extra_info("peername")
        logger.debug("icap.connection", addr=addr)

        try:
            # Keep-alive: handle multiple ICAP transactions per connection
            while True:
                parser = ICAPParser(reader)
                try:
                    request = await asyncio.wait_for(parser.parse(), timeout=30)
                except asyncio.TimeoutError:
                    break
                except (ConnectionResetError, asyncio.IncompleteReadError):
                    break
                except ValueError as e:
                    logger.warn("icap.parse_error", error=str(e))
                    break

                if request is None:
                    break  # Connection closed

                response = await handle_request(request, self.rewrite_fn)
                writer.write(response.serialize())
                await writer.drain()

                # Check Connection header
                conn = request.headers.get("connection", "").lower()
                if conn == "close":
                    break

        except Exception:
            logger.exception("icap.connection_error")
        finally:
            writer.close()
            try:
                await writer.wait_closed()
            except Exception:
                pass
