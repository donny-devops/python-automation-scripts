from datetime import datetime

from reminders import clip_text, parse_reminder_response, redact_secrets


def test_parse_reminder_valid():
    dt, message = parse_reminder_response(
        "Sure.\nREMINDER|2026-09-14T15:30:00|Stretch and hydrate\nDone."
    )
    assert dt == datetime.fromisoformat("2026-09-14T15:30:00")
    assert message == "Stretch and hydrate"


def test_parse_reminder_ignores_malformed():
    assert parse_reminder_response("") is None
    assert parse_reminder_response("REMINDER|not-a-date|x") is None
    assert parse_reminder_response("REMINDER|2026-09-14T15:30:00|") is None


def test_redact_secrets_and_clip():
    github_token = "ghp_" + ("abc" * 8)
    anthropic_token = "sk-ant-" + ("def" * 4)
    raw = f"token {github_token} and {anthropic_token}"
    redacted = redact_secrets(raw)
    assert github_token not in redacted
    assert anthropic_token not in redacted
    assert "[redacted]" in redacted
    assert clip_text("abcdef", 4) == "abcd…"
    assert clip_text("abcd", 4) == "abcd"
