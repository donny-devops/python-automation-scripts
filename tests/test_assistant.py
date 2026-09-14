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
    raw = "token ghp_abcdefghijklmnopqrstuvwx and sk-ant-abcdefghijk"
    redacted = redact_secrets(raw)
    assert "ghp_" not in redacted
    assert "sk-ant-abcdefghijk" not in redacted
    assert "[redacted]" in redacted
    assert clip_text("abcdef", 4) == "abcd…"
    assert clip_text("abcd", 4) == "abcd"
