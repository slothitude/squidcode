"""Tests for HTML parser."""

from squidcode.rewriter.html_parser import parse_html


class TestParseHTML:
    def test_extracts_paragraphs(self, sample_html):
        result = parse_html(sample_html)
        assert len(result.text_nodes) >= 3
        assert result.modified_html  # non-empty

    def test_assigns_ai_ids(self, sample_html):
        result = parse_html(sample_html)
        ids = [n.ai_id for n in result.text_nodes]
        assert ids[0] == "sq-0"
        assert ids[1] == "sq-1"
        assert len(set(ids)) == len(ids)  # all unique

    def test_data_attributes_in_html(self, sample_html):
        result = parse_html(sample_html)
        assert 'data-ai-id="sq-0"' in result.modified_html

    def test_skips_short_paragraphs(self, sample_html):
        result = parse_html(sample_html)
        texts = [n.original_text for n in result.text_nodes]
        assert "Short" not in texts

    def test_preserves_text(self, sample_html):
        result = parse_html(sample_html)
        assert any("semantic caching" in n.original_text for n in result.text_nodes)

    def test_empty_html(self):
        result = parse_html("<html><body></body></html>")
        assert len(result.text_nodes) == 0

    def test_minimal_html(self):
        result = parse_html("<p>Hi</p>")
        assert len(result.text_nodes) == 0  # too short (< 10 chars)

    def test_exact_threshold(self):
        result = parse_html("<p>1234567890</p>")
        assert len(result.text_nodes) == 1

    def test_below_threshold(self):
        result = parse_html("<p>123456789</p>")
        assert len(result.text_nodes) == 0

    def test_skips_script_contents(self):
        html = "<html><body><script><p>This should be skipped entirely from rewrite</p></script></body></html>"
        result = parse_html(html)
        assert len(result.text_nodes) == 0
