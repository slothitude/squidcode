"""Tests for LLM client with mocked OpenAI."""

import pytest

from squidcode.llm.prompts import build_system_prompt, build_user_prompt
from squidcode.llm.client import LLMClient
from squidcode.rag.retriever import RAGContext


class TestPrompts:
    def test_system_prompt_default_style(self):
        prompt = build_system_prompt("clarity")
        assert "clarity" in prompt.lower()
        assert "ONLY the rewritten text" in prompt

    def test_system_prompt_all_styles(self):
        for style in ("clarity", "simplify", "formal", "eli5"):
            prompt = build_system_prompt(style)
            assert style in prompt.lower() or "professional" in prompt.lower()

    def test_system_prompt_with_rag(self):
        ctx = RAGContext(
            style_guides=["Use active voice"],
            glossary_terms=["API: Application Programming Interface"],
            examples=["Good: X. Bad: Y."],
        )
        prompt = build_system_prompt("clarity", ctx)
        assert "Use active voice" in prompt
        assert "API" in prompt
        assert "Good: X" in prompt

    def test_user_prompt_single(self):
        prompt = build_user_prompt(["Hello world text"], ["sq-0"])
        assert "---ID:sq-0---" in prompt
        assert "Hello world text" in prompt

    def test_user_prompt_batch(self):
        prompt = build_user_prompt(["Text A", "Text B"], ["sq-0", "sq-1"])
        assert "---ID:sq-0---" in prompt
        assert "---ID:sq-1---" in prompt


class TestLLMClient:
    """Tests use the prompt building; actual streaming requires a live API or deeper mocking."""
    pass
