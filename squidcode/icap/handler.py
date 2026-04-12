"""ICAP RESPMOD handler.

Decides whether to rewrite content (text/html) or pass through (everything else).
"""

from __future__ import annotations

import structlog

from squidcode.config import settings
from squidcode.icap.protocol import (
    ICAPRequest,
    ICAPResponse,
    get_content_type,
    make_200_response,
    make_204_response,
    make_options_response,
    replace_body_in_headers,
)

logger = structlog.get_logger("squidcode.icap")

ISTAG = "\"squidcode-1\""


async def handle_request(request: ICAPRequest, rewrite_fn=None) -> ICAPResponse:
    """Route ICAP request to the appropriate handler."""
    if request.method == "OPTIONS":
        return make_options_response(ISTAG)

    if request.method != "RESPMOD":
        logger.warn("icap.unsupported_method", method=request.method)
        return make_204_response(ISTAG)

    return await _handle_respmod(request, rewrite_fn)


async def _handle_respmod(request: ICAPRequest, rewrite_fn=None) -> ICAPResponse:
    """Handle RESPMOD: rewrite text/html, pass through everything else."""
    content_type = get_content_type(request.http_response_headers)

    if not _is_html(content_type):
        logger.debug("icap.pass_through", content_type=content_type)
        return make_204_response(ISTAG)

    body = request.http_response_body
    if not body:
        logger.debug("icap.empty_body")
        return make_204_response(ISTAG)

    logger.info("icap.rewrite", size=len(body), content_type=content_type)

    if rewrite_fn is None:
        # No rewrite function configured — pass through
        return make_204_response(ISTAG)

    try:
        new_body = await rewrite_fn(body)
    except Exception:
        logger.exception("icap.rewrite_error")
        return make_204_response(ISTAG)

    if new_body is None:
        return make_204_response(ISTAG)

    new_headers = replace_body_in_headers(request.http_response_headers, new_body)
    return make_200_response(new_headers, new_body, ISTAG)


def _is_html(content_type: str) -> bool:
    """Check if content type indicates HTML."""
    ct = content_type.lower()
    return "text/html" in ct or "application/xhtml" in ct
