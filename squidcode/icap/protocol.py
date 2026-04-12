"""ICAP protocol parsing and serialization.

Handles the ICAP v1.0 protocol used between Squid and our server.
Key concepts:
  - Encapsulated header gives byte offsets for HTTP req-hdr, res-hdr, res-body
  - ICAP chunked encoding: each chunk is HEX_SIZE\\r\\n DATA \\r\\n, terminated by 0\\r\\n\\r\\n
  - 204 No Content = pass through unchanged
  - 200 OK with body = modified content
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class ICAPRequest:
    method: str
    uri: str
    version: str
    headers: dict[str, str] = field(default_factory=dict)
    http_request_headers: bytes = b""
    http_response_headers: bytes = b""
    http_response_body: bytes = b""
    preview_body: bytes = b""
    is_preview: bool = False
    preview_eof: bool = False


@dataclass
class ICAPResponse:
    status: int
    reason: str
    headers: dict[str, str] = field(default_factory=dict)
    http_response_headers: bytes = b""
    http_response_body: bytes = b""

    def serialize(self) -> bytes:
        parts = [f"ICAP/1.0 {self.status} {self.reason}\r\n"]
        for k, v in self.headers.items():
            parts.append(f"{k}: {v}\r\n")

        if self.status == 204:
            # No body needed for 204
            parts.append("\r\n")
            return "".join(parts).encode()

        if self.status == 100:
            parts.append("\r\n")
            return "".join(parts).encode()

        # 200 OK with encapsulated HTTP response
        enc_parts = []
        offset = 0

        if self.http_response_headers:
            enc_parts.append(f"res-hdr={offset}")
            offset += len(self.http_response_headers) + 2  # +2 for \r\n

        if self.http_response_body:
            enc_parts.append(f"res-body={offset}")

        if enc_parts:
            parts.append(f"Encapsulated: {', '.join(enc_parts)}\r\n")

        parts.append("\r\n")

        if self.http_response_headers:
            parts.append(self.http_response_headers.decode("utf-8", errors="replace"))
            parts.append("\r\n")

        if self.http_response_body:
            parts.append(_encode_icap_chunks(self.http_response_body))

        return "".join(parts).encode()


def _encode_icap_chunks(body: bytes) -> str:
    """Encode bytes into ICAP chunked format."""
    chunk_size = 4096
    parts = []
    for i in range(0, len(body), chunk_size):
        chunk = body[i : i + chunk_size]
        parts.append(f"{len(chunk):x}\r\n")
        parts.append(chunk.decode("utf-8", errors="replace"))
        parts.append("\r\n")
    parts.append("0\r\n\r\n")
    return "".join(parts)


class ICAPParser:
    """Incremental ICAP request parser.

    Reads from an asyncio StreamReader and returns a parsed ICAPRequest.
    """

    def __init__(self, reader):
        self.reader = reader

    async def parse(self) -> Optional[ICAPRequest]:
        """Parse one complete ICAP request. Returns None on connection close."""
        # Request line
        line = await self._readline()
        if not line:
            return None

        match = re.match(r"(\w+)\s+(\S+)\s+ICAP/(\d\.\d)", line)
        if not match:
            raise ValueError(f"Invalid ICAP request line: {line!r}")

        req = ICAPRequest(
            method=match.group(1),
            uri=match.group(2),
            version=match.group(3),
        )

        # Headers
        while True:
            hdr_line = await self._readline()
            if hdr_line is None or hdr_line.strip() == "":
                break
            if ":" in hdr_line:
                key, _, val = hdr_line.partition(":")
                req.headers[key.strip().lower()] = val.strip()

        # Parse Encapsulated header to know what sections follow
        enc_header = req.headers.get("encapsulated", "")
        sections = _parse_encapsulated(enc_header)

        # Determine body offset boundary
        has_body = "res-body" in sections or "req-body" in sections or "null-body" in sections
        body_section = None
        for name in ("res-body", "req-body"):
            if name in sections:
                body_section = name
                break

        # Read header sections
        for name, (start, end) in sections.items():
            if name == "req-hdr":
                req.http_request_headers = await self._read_exact(end - start)
                await self._readline()  # blank line after headers
            elif name == "res-hdr":
                req.http_response_headers = await self._read_exact(end - start)
                await self._readline()  # blank line after headers
            elif name == "null-body":
                pass  # no body
            elif name in ("res-body", "req-body"):
                # Body uses ICAP chunked encoding
                body = await self._read_icap_chunks()
                if name == "res-body":
                    req.http_response_body = body
                # For req-body, we don't need it in RESPMOD for our use case

        # Handle preview
        preview_size = int(req.headers.get("preview", "0"))
        if preview_size > 0:
            req.is_preview = True
            # We've already read everything; preview is handled by the fact
            # that the full body may not have been sent yet.
            # For v0.1 with icap_preview_enable off, this won't be used.

        return req

    async def _readline(self) -> Optional[str]:
        line = await self.reader.readline()
        if not line:
            return None
        return line.decode("utf-8", errors="replace").rstrip("\r\n")

    async def _read_exact(self, n: int) -> bytes:
        return await self.reader.readexactly(n)

    async def _read_icap_chunks(self) -> bytes:
        """Read ICAP chunked transfer encoding until 0-size terminator."""
        body = bytearray()
        while True:
            size_line = await self._readline()
            if size_line is None:
                break
            size_str = size_line.strip()
            if not size_str:
                continue
            chunk_size = int(size_str, 16)
            if chunk_size == 0:
                # Read trailing \r\n after 0
                await self._readline()
                break
            chunk_data = await self.reader.readexactly(chunk_size)
            body.extend(chunk_data)
            # Read trailing \r\n after chunk data
            await self._readline()
        return bytes(body)


def _parse_encapsulated(header: str) -> dict[str, tuple[int, int]]:
    """Parse Encapsulated header into {section_name: (start, end)} offsets."""
    if not header:
        return {}

    sections: dict[str, tuple[int, int]] = {}
    parts = [p.strip() for p in header.split(",")]

    entries = []
    for part in parts:
        if "=" not in part:
            continue
        name, _, offset_str = part.partition("=")
        entries.append((name.strip(), int(offset_str.strip())))

    # Sort by offset to compute end boundaries
    entries.sort(key=lambda x: x[1])

    for i, (name, start) in enumerate(entries):
        if i + 1 < len(entries):
            end = entries[i + 1][1]
        else:
            end = None  # last entry extends to end of encapsulated data
        sections[name] = (start, end if end is not None else start)

    return sections


def make_204_response(istag: str = "\"squidcode-1\"") -> ICAPResponse:
    """Create a 204 No Content response (pass-through)."""
    return ICAPResponse(
        status=204,
        reason="No Content",
        headers={
            "ISTag": istag,
            "Connection": "keep-alive",
        },
    )


def make_100_continue(istag: str = "\"squidcode-1\"") -> ICAPResponse:
    """Create a 100 Continue response (for preview handling)."""
    return ICAPResponse(
        status=100,
        reason="Continue",
        headers={"ISTag": istag},
    )


def make_options_response(istag: str = "\"squidcode-1\"") -> ICAPResponse:
    """Create an OPTIONS response advertising our capabilities."""
    return ICAPResponse(
        status=200,
        reason="OK",
        headers={
            "Methods": "RESPMOD",
            "ISTag": istag,
            "Allow": "204",
            "Preview": "4096",
            "Connection": "keep-alive",
        },
    )


def make_200_response(
    http_headers: bytes,
    http_body: bytes,
    istag: str = "\"squidcode-1\"",
) -> ICAPResponse:
    """Create a 200 OK response with modified HTTP content."""
    return ICAPResponse(
        status=200,
        reason="OK",
        headers={
            "ISTag": istag,
            "Connection": "keep-alive",
        },
        http_response_headers=http_headers,
        http_response_body=http_body,
    )


def get_content_type(http_headers: bytes) -> str:
    """Extract Content-Type from raw HTTP response headers."""
    for line in http_headers.decode("utf-8", errors="replace").split("\r\n"):
        if line.lower().startswith("content-type:"):
            return line.split(":", 1)[1].strip()
    return ""


def replace_body_in_headers(http_headers: bytes, new_body: bytes) -> bytes:
    """Update Content-Length in HTTP headers to match new body size."""
    header_str = http_headers.decode("utf-8", errors="replace")
    lines = header_str.split("\r\n")
    new_lines = []
    for line in lines:
        if line.lower().startswith("content-length:"):
            new_lines.append(f"Content-Length: {len(new_body)}")
        else:
            new_lines.append(line)
    return "\r\n".join(new_lines).encode("utf-8")
