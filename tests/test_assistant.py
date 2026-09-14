from datetime import datetime

import pytest

from reminders import clip_text, parse_reminder_response, redact_secrets, strip_wake_word
from weather import (
    OPENWEATHER_HOST,
    WeatherError,
    assert_openweather_url,
    build_weather_url,
    format_weather_payload,
)


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


def test_strip_wake_word():
    assert strip_wake_word("Aria, status report", "aria") == "status report"
    assert strip_wake_word("what time is it", "aria") is None
    assert strip_wake_word("hello", "") == "hello"
    assert strip_wake_word("ARIA", "aria") == ""


def test_openweather_url_stays_on_fixed_host():
    url = build_weather_url("Miami", "placeholder-key")
    assert OPENWEATHER_HOST in url
    assert assert_openweather_url(url) == url
    with pytest.raises(WeatherError):
        assert_openweather_url("https://evil.example/data/2.5/weather")
    summary = format_weather_payload(
        {"name": "Miami", "weather": [{"description": "clear sky"}], "main": {"temp": 29.4}}
    )
    assert "Miami" in summary
    assert "clear sky" in summary
