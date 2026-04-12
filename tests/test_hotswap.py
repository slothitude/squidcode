"""Real integration test: spin up ICAP + SSE servers, send live traffic."""

import asyncio
import json
import time
import threading
import sys

import httpx
import pytest
import uvicorn

from squidcode.icap.server import ICAPServer
from squidcode.sse.endpoint import create_sse_app
from squidcode.sse.manager import SSEManager
from squidcode.rewriter.html_parser import parse_html
from squidcode.rewriter.script_injector import inject_runtime
from squidcode.utils.session import generate_session_id
from squidcode.config import settings


# ── Helpers ──────────────────────────────────────────────────────────────────

def _build_icap_respmod(html_body: bytes) -> bytes:
    """Build a raw ICAP RESPMOD request with the given HTML body."""
    http_res_hdr = (
        f"HTTP/1.1 200 OK\r\n"
        f"Content-Type: text/html; charset=utf-8\r\n"
        f"Content-Length: {len(html_body)}\r\n"
    ).encode()

    # ICAP chunked body
    chunk = f"{len(html_body):x}\r\n".encode() + html_body + b"\r\n0\r\n\r\n"

    enc_parts = []
    offset = 0
    enc_parts.append(f"res-hdr={offset}")
    offset += len(http_res_hdr) + 2
    enc_parts.append(f"res-body={offset}")

    request_line = b"RESPMOD icap://127.0.0.1:1344/squidcode ICAP/1.0\r\n"
    headers = (
        f"Host: 127.0.0.1\r\n"
        f"Connection: close\r\n"
        f"Encapsulated: {', '.join(enc_parts)}\r\n"
        f"\r\n"
    ).encode()

    return request_line + headers + http_res_hdr + b"\r\n" + chunk


def _build_icap_options() -> bytes:
    return (
        b"OPTIONS icap://127.0.0.1:1344/squidcode ICAP/1.0\r\n"
        b"Host: 127.0.0.1\r\n"
        b"Connection: close\r\n"
        b"\r\n"
    )


def _build_icap_respmod_non_html(body: bytes, content_type: str = "application/json") -> bytes:
    """Build ICAP RESPMOD for non-HTML content."""
    http_res_hdr = (
        f"HTTP/1.1 200 OK\r\n"
        f"Content-Type: {content_type}\r\n"
        f"Content-Length: {len(body)}\r\n"
    ).encode()
    chunk = f"{len(body):x}\r\n".encode() + body + b"\r\n0\r\n\r\n"

    enc_parts = []
    offset = 0
    enc_parts.append(f"res-hdr={offset}")
    offset += len(http_res_hdr) + 2
    enc_parts.append(f"res-body={offset}")

    request_line = b"RESPMOD icap://127.0.0.1:1344/squidcode ICAP/1.0\r\n"
    headers = (
        f"Host: 127.0.0.1\r\n"
        f"Connection: close\r\n"
        f"Encapsulated: {', '.join(enc_parts)}\r\n"
        f"\r\n"
    ).encode()

    return request_line + headers + http_res_hdr + b"\r\n" + chunk


# ── Server fixtures ──────────────────────────────────────────────────────────

ICAP_PORT = 11344  # non-default to avoid conflicts
SSE_PORT = 18080


@pytest.fixture(scope="module")
def sse_manager_module():
    return SSEManager()


@pytest.fixture(scope="module")
def sse_server(sse_manager_module):
    """Start SSE server in a background thread."""
    app = create_sse_app(sse_manager_module)
    config = uvicorn.Config(app, host="127.0.0.1", port=SSE_PORT, log_level="error")
    server = uvicorn.Server(config)

    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    # Wait for server to be ready
    for _ in range(40):
        try:
            resp = httpx.get(f"http://127.0.0.1:{SSE_PORT}/squidcode/health", timeout=1)
            if resp.status_code == 200:
                break
        except Exception:
            pass
        time.sleep(0.1)

    yield server
    server.should_exit = True
    thread.join(timeout=5)


@pytest.fixture(scope="module")
def icap_server(sse_manager_module):
    """Start ICAP server in a background asyncio thread."""

    async def rewrite_fn(body: bytes) -> bytes | None:
        html = body.decode("utf-8", errors="replace")
        page = parse_html(html)
        if not page.text_nodes:
            return None
        session_id = generate_session_id()
        sse_manager_module.create_session(session_id)
        modified = inject_runtime(page.modified_html, session_id, f"http://127.0.0.1:{SSE_PORT}")

        # Simulate pipeline pushing updates for all nodes
        for node in page.text_nodes:
            await sse_manager_module.push_update(
                session_id, node.ai_id, f"[rewritten] {node.original_text}"
            )

        return modified.encode("utf-8")

    icap = ICAPServer(host="127.0.0.1", port=ICAP_PORT, rewrite_fn=rewrite_fn)

    loop = asyncio.new_event_loop()

    def run_server():
        asyncio.set_event_loop(loop)
        loop.run_until_complete(icap.start())
        loop.run_forever()

    thread = threading.Thread(target=run_server, daemon=True)
    thread.start()
    time.sleep(0.5)  # let it bind

    yield icap

    loop.call_soon_threadsafe(loop.stop)


# ── Tests ────────────────────────────────────────────────────────────────────

class TestHotswapServers:
    @pytest.fixture(autouse=True)
    def _require_servers(self, sse_server, icap_server):
        """Ensure both servers are up before each test."""
        pass

    def test_icap_options(self):
        """ICAP OPTIONS returns correct capabilities."""
        sock = self._icap_connect()
        sock.sendall(_build_icap_options())

        data = sock.recv(4096)
        sock.close()

        response = data.decode("utf-8", errors="replace")
        assert "200 OK" in response
        assert "Methods: RESPMOD" in response
        assert "Allow: 204" in response

    def test_icap_html_rewrite(self):
        """ICAP RESPMOD with HTML returns 200 with modified content."""
        html = (
            "<html><head><title>Test</title></head><body>"
            "<p>This is the first paragraph with enough text to be selected for rewriting by our system.</p>"
            "<p>Second paragraph discussing the semantic caching layer and its benefits for response latency.</p>"
            "<p>Short</p>"
            "</body></html>"
        ).encode()

        sock = self._icap_connect()
        sock.sendall(_build_icap_respmod(html))

        data = b""
        while True:
            chunk = sock.recv(65536)
            if not chunk:
                break
            data += chunk
        sock.close()

        response = data.decode("utf-8", errors="replace")
        assert "200 OK" in response
        assert 'data-ai-id="sq-0"' in response
        assert 'data-ai-id="sq-1"' in response
        assert "squidcode-session" in response
        assert "EventSource" in response
        # Short paragraph should NOT have an id
        assert "sq-2" not in response

    def test_icap_non_html_passthrough(self):
        """ICAP RESPMOD with JSON returns 204 (pass-through)."""
        body = b'{"message": "hello world"}'

        sock = self._icap_connect()
        sock.sendall(_build_icap_respmod_non_html(body))

        data = sock.recv(4096)
        sock.close()

        response = data.decode("utf-8", errors="replace")
        assert "204 No Content" in response

    def test_icap_image_passthrough(self):
        """ICAP RESPMOD with image content type returns 204."""
        body = b"\x89PNG\r\n\x1a\n" + b"\x00" * 100

        sock = self._icap_connect()
        sock.sendall(_build_icap_respmod_non_html(body, "image/png"))

        data = sock.recv(4096)
        sock.close()

        response = data.decode("utf-8", errors="replace")
        assert "204 No Content" in response

    def test_sse_health(self):
        """SSE health endpoint returns ok."""
        resp = httpx.get(f"http://127.0.0.1:{SSE_PORT}/squidcode/health", timeout=5)
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"

    def test_sse_stream_and_push(self, sse_manager_module):
        """SSE endpoint streams events pushed by the pipeline."""
        session_id = generate_session_id()
        queue = sse_manager_module.create_session(session_id)

        # Push updates in a background thread
        def push_updates():
            time.sleep(0.3)
            loop = asyncio.new_event_loop()
            loop.run_until_complete(
                sse_manager_module.push_update(session_id, "sq-0", "Rewritten first paragraph")
            )
            loop.run_until_complete(
                sse_manager_module.push_update(session_id, "sq-1", "Rewritten second paragraph")
            )
            loop.close()

        pusher = threading.Thread(target=push_updates, daemon=True)
        pusher.start()

        # Connect to SSE and read events
        events = []
        with httpx.stream(
            "GET",
            f"http://127.0.0.1:{SSE_PORT}/squidcode/sse/{session_id}",
            timeout=10,
        ) as resp:
            assert resp.status_code == 200
            assert "text/event-stream" in resp.headers.get("content-type", "")

            deadline = time.time() + 5
            for line in resp.iter_lines():
                if line.startswith("data: "):
                    payload = json.loads(line[6:])
                    events.append(payload)
                    if len(events) == 2:
                        break
                if time.time() > deadline:
                    break

        assert len(events) == 2
        assert events[0] == {"id": "sq-0", "text": "Rewritten first paragraph"}
        assert events[1] == {"id": "sq-1", "text": "Rewritten second paragraph"}

    def test_sse_cors_headers(self):
        """SSE endpoint includes CORS headers for cross-origin browser access."""
        session_id = generate_session_id()
        with httpx.stream(
            "GET",
            f"http://127.0.0.1:{SSE_PORT}/squidcode/sse/{session_id}",
            timeout=5,
            headers={"Origin": "https://example.com"},
        ) as resp:
            assert resp.status_code == 200
            assert "access-control-allow-origin" in resp.headers
            assert resp.headers["access-control-allow-origin"] == "*"

    def test_full_roundtrip(self, sse_manager_module):
        """End-to-end: ICAP rewrites HTML → session created → queue has updates."""
        html = (
            "<html><head><title>E2E Test</title></head><body>"
            "<h1>Important heading for the integration test page</h1>"
            "<p>This paragraph must be long enough to qualify for the rewrite pipeline processing step.</p>"
            "<p>Another paragraph that discusses the retrieval augmented generation approach we use here.</p>"
            "</body></html>"
        ).encode()

        # Step 1: Send through ICAP
        sock = self._icap_connect()
        sock.sendall(_build_icap_respmod(html))

        data = b""
        while True:
            chunk = sock.recv(65536)
            if not chunk:
                break
            data += chunk
        sock.close()

        response = data.decode("utf-8", errors="replace")
        assert "200 OK" in response
        assert 'data-ai-id="sq-' in response

        # Step 2: Extract session ID from the modified HTML
        import re
        match = re.search(r'squidcode-session.*?content="([^"]+)"', response)
        if not match:
            match = re.search(r'content="([^"]+)".*?squidcode-session', response)
        assert match, "Session meta tag not found in ICAP response"
        session_id = match.group(1)

        # Step 3: Verify the SSE queue has the updates (pushed during rewrite_fn)
        queue = sse_manager_module.get_queue(session_id)
        assert queue is not None, f"No SSE session for {session_id}"

        # Drain all queued messages (non-blocking, synchronous check via asyncio)
        events = []
        while not queue.empty():
            payload = queue.get_nowait()
            events.append(json.loads(payload))

        assert len(events) >= 2, f"Expected >=2 events, got {len(events)}"
        for ev in events:
            assert ev["id"].startswith("sq-")
            assert "[rewritten]" in ev["text"]

    def _icap_connect(self):
        """Open a TCP connection to the ICAP server."""
        import socket
        sock = socket.create_connection(("127.0.0.1", ICAP_PORT), timeout=5)
        sock.settimeout(5)
        return sock
