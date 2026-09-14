"""Pure helpers for reminder parsing and secret redaction."""

from __future__ import annotations

import re
from datetime import datetime

# Obvious credential patterns that should never be forwarded to a model.
_SECRET_RE = re.compile(
    r"(?i)("
    r"sk-[A-Za-z0-9_\-]{8,}"
    r"|sk-ant-[A-Za-z0-9_\-]{8,}"
    r"|ghp_[A-Za-z0-9]{20,}"
    r"|github_pat_[A-Za-z0-9_]{20,}"
    r"|AKIA[0-9A-Z]{16}"
    r"|xox[baprs]-[A-Za-z0-9-]{10,}"
    r")"
)


def parse_reminder_response(response: str) -> tuple[datetime, str] | None:
    """Parse REMINDER|<ISO datetime>|<message> from an AI response."""
    if not response:
        return None
    for line in response.splitlines():
        stripped = line.strip()
        if not stripped.startswith("REMINDER|"):
            continue
        parts = stripped.split("|", 2)
        if len(parts) != 3:
            continue
        try:
            dt = datetime.fromisoformat(parts[1].strip())
        except ValueError:
            continue
        message = parts[2].strip()
        if message:
            return dt, message
    return None


def redact_secrets(text: str) -> str:
    """Replace credential-like tokens before sending text to an API."""
    if not text:
        return ""
    return _SECRET_RE.sub("[redacted]", text)


def clip_text(text: str, limit: int = 2000) -> str:
    if len(text) <= limit:
        return text
    return text[:limit] + "…"
