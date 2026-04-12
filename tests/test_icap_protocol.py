"""Tests for ICAP protocol parsing and serialization."""

import pytest

from squidcode.icap.protocol import (
    ICAPRequest,
    ICAPResponse,
    get_content_type,
    make_200_response,
    make_204_response,
    make_options_response,
    replace_body_in_headers,
)


class TestICAPResponse:
    def test_204_response(self):
        resp = make_204_response()
        raw = resp.serialize()
        assert b"204 No Content" in raw
        assert b"ISTag" in raw
        # No body for 204
        assert raw.endswith(b"\r\n\r\n")

    def test_100_continue(self):
        from squidcode.icap.protocol import make_100_continue
        resp = make_100_continue()
        raw = resp.serialize()
        assert b"100 Continue" in raw

    def test_options_response(self):
        resp = make_options_response()
        raw = resp.serialize()
        assert b"200 OK" in raw
        assert b"Methods: RESPMOD" in raw
        assert b"Allow: 204" in raw

    def test_200_response_with_body(self):
        headers = b"HTTP/1.1 200 OK\r\nContent-Type: text/html\r\nContent-Length: 13"
        body = b"<p>Hello</p>\n"
        resp = make_200_response(headers, body)
        raw = resp.serialize()
        assert b"200 OK" in raw
        assert b"Encapsulated" in raw
        assert b"<p>Hello</p>" in raw


class TestGetContentType:
    def test_html(self):
        headers = b"HTTP/1.1 200 OK\r\nContent-Type: text/html; charset=utf-8\r\n"
        assert "text/html" in get_content_type(headers)

    def test_json(self):
        headers = b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\n"
        assert "application/json" in get_content_type(headers)

    def test_missing(self):
        headers = b"HTTP/1.1 200 OK\r\n"
        assert get_content_type(headers) == ""


class TestReplaceBodyInHeaders:
    def test_updates_content_length(self):
        headers = b"HTTP/1.1 200 OK\r\nContent-Length: 100\r\nContent-Type: text/html"
        new_body = b"<p>New content that is different</p>"
        result = replace_body_in_headers(headers, new_body)
        assert f"Content-Length: {len(new_body)}".encode() in result
        assert b"Content-Type: text/html" in result

    def test_no_content_length(self):
        headers = b"HTTP/1.1 200 OK\r\nContent-Type: text/html"
        new_body = b"<p>Content</p>"
        result = replace_body_in_headers(headers, new_body)
        assert b"Content-Type: text/html" in result
