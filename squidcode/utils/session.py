"""Session ID generation."""

import uuid


def generate_session_id() -> str:
    return str(uuid.uuid4())
