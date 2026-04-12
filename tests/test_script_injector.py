"""Tests for script injection."""

from squidcode.rewriter.script_injector import inject_runtime


class TestInjectRuntime:
    def test_injects_meta_tag(self, sample_html):
        result = inject_runtime(sample_html, "test-session-123", "http://localhost:8080")
        assert 'name="squidcode-session"' in result
        assert 'content="test-session-123"' in result

    def test_injects_script(self, sample_html):
        result = inject_runtime(sample_html, "test-session", "http://localhost:8080")
        assert "<script" in result
        assert "EventSource" in result

    def test_replaces_origin_placeholder(self, sample_html):
        result = inject_runtime(sample_html, "test-session", "http://localhost:8080")
        assert "http://localhost:8080" in result
        assert "{{SSE_ORIGIN}}" not in result

    def test_minimal_html(self):
        html = "<html><body><p>Test paragraph with enough text to parse correctly.</p></body></html>"
        result = inject_runtime(html, "sid", "http://localhost:8080")
        assert 'content="sid"' in result
        assert "EventSource" in result

    def test_no_head_tag(self):
        html = "<p>Some paragraph text that should work without a head tag.</p>"
        result = inject_runtime(html, "sid", "http://localhost:8080")
        assert 'content="sid"' in result
