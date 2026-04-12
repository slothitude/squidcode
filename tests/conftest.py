"""Shared test fixtures."""

from pathlib import Path

import pytest

FIXTURES_DIR = Path(__file__).parent / "fixtures"


@pytest.fixture
def sample_html() -> str:
    return (FIXTURES_DIR / "sample_page.html").read_text()


@pytest.fixture
def sample_style_guide() -> str:
    return (FIXTURES_DIR / "sample_style_guide.md").read_text()
