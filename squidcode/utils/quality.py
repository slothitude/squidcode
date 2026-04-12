"""Output quality validation."""

from __future__ import annotations

# Tokens that indicate the LLM broke out of the rewrite task
SUSPICIOUS_TOKENS = frozenset({
    "sure!", "here's the rewritten", "i've rewritten", "here are",
    "certainly!", "of course!", "let me help",
})

MAX_LENGTH_DELTA = 0.30  # rewritten can be ±30% of original length


def check_quality(original: str, rewritten: str) -> bool:
    """Validate that a rewrite is acceptable.

    Checks:
      - Length is within ±30% of original
      - No suspicious instruction-following tokens
    """
    if not rewritten or not rewritten.strip():
        return False

    # Length check
    orig_len = len(original)
    new_len = len(rewritten)
    if orig_len > 0:
        delta = abs(new_len - orig_len) / orig_len
        if delta > MAX_LENGTH_DELTA:
            return False

    # Suspicious token check
    lower = rewritten.lower()
    for token in SUSPICIOUS_TOKENS:
        if token in lower:
            return False

    return True
