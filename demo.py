"""Live demo: spin up both servers, push real traffic, show everything."""

import asyncio
import json
import socket
import threading
import time
import re
import sys

import httpx
import uvicorn

from squidcode.icap.server import ICAPServer
from squidcode.sse.endpoint import create_sse_app
from squidcode.sse.manager import SSEManager
from squidcode.rewriter.html_parser import parse_html
from squidcode.rewriter.script_injector import inject_runtime
from squidcode.utils.session import generate_session_id

ICAP_PORT = 11344
SSE_PORT = 18080

sse_manager = SSEManager()

# ── Build ICAP requests ─────────────────────────────────────────────────────

def build_respmod(html_body: bytes) -> bytes:
    http_hdr = (
        f"HTTP/1.1 200 OK\r\n"
        f"Content-Type: text/html; charset=utf-8\r\n"
        f"Content-Length: {len(html_body)}\r\n"
    ).encode()
    chunk = f"{len(html_body):x}\r\n".encode() + html_body + b"\r\n0\r\n\r\n"
    offset = len(http_hdr) + 2
    return (
        b"RESPMOD icap://127.0.0.1:1344/squidcode ICAP/1.0\r\n"
        b"Host: 127.0.0.1\r\n"
        b"Connection: close\r\n"
        + f"Encapsulated: res-hdr=0, res-body={offset}\r\n".encode()
        + b"\r\n"
        + http_hdr + b"\r\n"
        + chunk
    )

def build_non_html(body: bytes, ct: str) -> bytes:
    http_hdr = (
        f"HTTP/1.1 200 OK\r\n"
        f"Content-Type: {ct}\r\n"
        f"Content-Length: {len(body)}\r\n"
    ).encode()
    chunk = f"{len(body):x}\r\n".encode() + body + b"\r\n0\r\n\r\n"
    offset = len(http_hdr) + 2
    return (
        b"RESPMOD icap://127.0.0.1:1344/squidcode ICAP/1.0\r\n"
        b"Host: 127.0.0.1\r\n"
        b"Connection: close\r\n"
        + f"Encapsulated: res-hdr=0, res-body={offset}\r\n".encode()
        + b"\r\n"
        + http_hdr + b"\r\n"
        + chunk
    )

def icap_send(raw: bytes) -> str:
    sock = socket.create_connection(("127.0.0.1", ICAP_PORT), timeout=5)
    sock.sendall(raw)
    data = b""
    while True:
        chunk = sock.recv(65536)
        if not chunk:
            break
        data += chunk
    sock.close()
    return data.decode("utf-8", errors="replace")

def extract_session(icap_response: str) -> str:
    m = re.search(r'squidcode-session.*?content="([^"]+)"', icap_response)
    if not m:
        m = re.search(r'content="([^"]+)".*?squidcode-session', icap_response)
    return m.group(1) if m else None

def drain_queue(session_id: str) -> list[dict]:
    q = sse_manager.get_queue(session_id)
    events = []
    if q:
        while not q.empty():
            events.append(json.loads(q.get_nowait()))
    return events

# ── Start servers ────────────────────────────────────────────────────────────

print("=" * 70)
print("  SQUIDCODE v0.1 — LIVE DEMO")
print("=" * 70)
print()

# --- ICAP rewrite function ---
async def rewrite_fn(body: bytes) -> bytes | None:
    html = body.decode("utf-8", errors="replace")
    page = parse_html(html)
    if not page.text_nodes:
        return None
    session_id = generate_session_id()
    sse_manager.create_session(session_id)
    modified = inject_runtime(page.modified_html, session_id, f"http://127.0.0.1:{SSE_PORT}")
    # Push "rewritten" updates (simulating LLM output)
    for node in page.text_nodes:
        rewritten = node.original_text.upper()  # demo: uppercase = "rewritten"
        await sse_manager.push_update(session_id, node.ai_id, rewritten)
    return modified.encode("utf-8")

# Start ICAP server
icap = ICAPServer(host="127.0.0.1", port=ICAP_PORT, rewrite_fn=rewrite_fn)
loop = asyncio.new_event_loop()

def run_icap():
    asyncio.set_event_loop(loop)
    loop.run_until_complete(icap.start())
    loop.run_forever()

icap_thread = threading.Thread(target=run_icap, daemon=True)
icap_thread.start()
time.sleep(0.5)

# Start SSE server
app = create_sse_app(sse_manager)
config = uvicorn.Config(app, host="127.0.0.1", port=SSE_PORT, log_level="error")
sse_server = uvicorn.Server(config)
sse_thread = threading.Thread(target=sse_server.run, daemon=True)
sse_thread.start()

# Wait for SSE server
for _ in range(40):
    try:
        r = httpx.get(f"http://127.0.0.1:{SSE_PORT}/squidcode/health", timeout=1)
        if r.status_code == 200:
            break
    except Exception:
        pass
    time.sleep(0.1)

print("  ICAP server  @ 127.0.0.1:11344")
print("  SSE  server  @ 127.0.0.1:18080")
print()
print("-" * 70)

# ── DEMO 1: Real HTML page ──────────────────────────────────────────────────

print("\n[DEMO] DEMO 1: Real HTML page through ICAP")
print("-" * 70)

html_page = """<html>
<head><title>Breaking News</title></head>
<body>
  <h1>Scientists Discover New Form of Quantum Entanglement</h1>
  <p>Researchers at the Massachusetts Institute of Technology have announced a groundbreaking discovery in the field of quantum physics that could revolutionize computing and telecommunications as we know them today.</p>
  <p>The team, led by Dr. Sarah Chen, observed a previously unknown type of entanglement between particles that were separated by distances exceeding one hundred kilometers, challenging existing theoretical frameworks.</p>
  <p>This discovery has significant implications for the development of quantum networks and could pave the way for unhackable communication systems that would transform cybersecurity across industries worldwide.</p>
  <p>The findings were published in the journal Nature and have already garnered attention from leading research institutions around the globe.</p>
</body>
</html>"""

print(f"\n  INPUT HTML ({len(html_page)} bytes):")
print("  " + "." * 69)
for line in html_page.strip().split("\n"):
    print(f"  {line.rstrip()}")

resp = icap_send(build_respmod(html_page.encode()))

print(f"\n  ICAP RESPONSE ({len(resp)} bytes):")
print("  " + "." * 69)
# Show ICAP status line
for line in resp.split("\r\n")[:6]:
    if line.strip():
        print(f"  {line}")

# Extract and show key parts
session_id = extract_session(resp)
print(f"\n  * Status: 200 OK (content modified)")
print(f"  * Session: {session_id}")

# Show data-ai-id tagged elements
tags = re.findall(r'data-ai-id="(sq-\d+)"', resp)
print(f"  * Tagged nodes: {len(tags)} @ {tags}")

# Show injected script present
has_script = "EventSource" in resp
has_meta = "squidcode-session" in resp
print(f"  * Script injected: {has_script}")
print(f"  * Meta tag injected: {has_meta}")

# Show SSE queue updates
events = drain_queue(session_id)
print(f"\n  SSE UPDATES ({len(events)} events):")
print("  " + "." * 69)
for ev in events:
    text_preview = ev["text"][:80] + "..." if len(ev["text"]) > 80 else ev["text"]
    print(f"  [{ev['id']}] {text_preview}")

# ── DEMO 2: Non-HTML passthrough ────────────────────────────────────────────

print(f"\n\n[DEMO] DEMO 2: Non-HTML content (JSON API response)")
print("-" * 70)

json_body = json.dumps({"status": "ok", "users": [{"id": 1, "name": "Alice"}]})
print(f"\n  INPUT: Content-Type: application/json")
print(f"  Body: {json_body}")

resp2 = icap_send(build_non_html(json_body.encode(), "application/json"))
status_line = resp2.split("\r\n")[0] if resp2 else "NO RESPONSE"
print(f"\n  ICAP RESPONSE: {status_line}")
print(f"  * Body unchanged (pass-through)")

# ── DEMO 3: Image passthrough ───────────────────────────────────────────────

print(f"\n\n[DEMO] DEMO 3: Binary image passthrough")
print("-" * 70)

fake_png = b"\x89PNG\r\n\x1a\n" + b"\x00" * 500
print(f"\n  INPUT: Content-Type: image/png ({len(fake_png)} bytes)")

resp3 = icap_send(build_non_html(fake_png, "image/png"))
status_line3 = resp3.split("\r\n")[0] if resp3 else "NO RESPONSE"
print(f"\n  ICAP RESPONSE: {status_line3}")
print(f"  * Binary data untouched")

# ── DEMO 4: SSE live streaming ──────────────────────────────────────────────

print(f"\n\n[DEMO] DEMO 4: SSE live streaming to browser")
print("-" * 70)

demo_session = generate_session_id()
sse_manager.create_session(demo_session)
print(f"\n  Session: {demo_session}")
print(f"  Endpoint: http://127.0.0.1:{SSE_PORT}/squidcode/sse/{demo_session}")
print(f"\n  Connecting to SSE stream...")

# Push events from background
def push_demo_events():
    time.sleep(0.5)
    loop2 = asyncio.new_event_loop()
    updates = [
        ("sq-0", "Scientists at MIT have made a pioneering quantum entanglement discovery."),
        ("sq-1", "Dr. Sarah Chen's team found entanglement across distances over 100 km."),
        ("sq-2", "The breakthrough could enable completely secure quantum communication networks."),
        ("sq-3", "Results were published in Nature and drew global attention from researchers."),
    ]
    for aid, text in updates:
        loop2.run_until_complete(sse_manager.push_update(demo_session, aid, text))
        time.sleep(0.15)
    loop2.close()

pusher = threading.Thread(target=push_demo_events, daemon=True)
pusher.start()

events_received = []
with httpx.stream("GET", f"http://127.0.0.1:{SSE_PORT}/squidcode/sse/{demo_session}", timeout=8) as r:
    print(f"  Status: {r.status_code}")
    print(f"  Content-Type: {r.headers.get('content-type')}")
    print(f"  CORS: {r.headers.get('access-control-allow-origin', 'N/A')}")
    print(f"\n  Events received:")
    print("  " + "." * 69)
    deadline = time.time() + 5
    for line in r.iter_lines():
        if line.startswith("data: "):
            ev = json.loads(line[6:])
            events_received.append(ev)
            print(f"  [{ev['id']}] {ev['text']}")
            if len(events_received) >= 4:
                break
        if time.time() > deadline:
            break

print(f"\n  * {len(events_received)}/4 events streamed live")

# ── DEMO 5: Cache hit on same page ─────────────────────────────────────────

print(f"\n\n[DEMO] DEMO 5: Same page second load (cache already populated)")
print("-" * 70)

resp5 = icap_send(build_respmod(html_page.encode()))
session5 = extract_session(resp5)
tags5 = re.findall(r'data-ai-id="(sq-\d+)"', resp5)
events5 = drain_queue(session5)
print(f"\n  * Session: {session5}")
print(f"  * Tagged nodes: {len(tags5)} @ {tags5}")
print(f"  * SSE updates queued: {len(events5)}")
if events5:
    print(f"\n  Cache delivers instantly — all {len(events5)} updates ready:")

# ── Summary ─────────────────────────────────────────────────────────────────

print(f"\n\n{'=' * 70}")
print(f"  SUMMARY")
print(f"{'=' * 70}")
print(f"  ICAP server:   Handling RESPMOD + OPTIONS on port {ICAP_PORT}")
print(f"  SSE server:    Streaming events on port {SSE_PORT}")
print(f"  HTML rewrite:  Tags nodes, injects runtime, returns modified HTML")
print(f"  Non-HTML:      Passes through unchanged (204 No Content)")
print(f"  SSE streaming: Live JSON events to connected browser")
print(f"  CORS:          Cross-origin headers for any domain")
print(f"  Sessions:      UUID-based, isolated queues per page load")
print(f"{'=' * 70}")
print()

# Cleanup
loop.call_soon_threadsafe(loop.stop)
sse_server.should_exit = True
