"""Optional OpenWeather briefing helper.

The request host is a constant. Callers must pass the returned URL through
`assert_openweather_url` before fetching so a future refactor cannot point
the client at an arbitrary host.
"""

from __future__ import annotations

from urllib.parse import urlencode, urlparse

OPENWEATHER_HOST = "api.openweathermap.org"
OPENWEATHER_PATH = "/data/2.5/weather"


class WeatherError(ValueError):
    """Raised when a weather request would leave the OpenWeather host."""


def build_weather_url(city: str, api_key: str) -> str:
    if not city or not city.strip():
        raise WeatherError("CITY is required for weather lookup")
    if not api_key or not api_key.strip():
        raise WeatherError("WEATHER_API_KEY is required for weather lookup")
    query = urlencode(
        {"q": city.strip(), "appid": api_key.strip(), "units": "metric"}
    )
    return f"https://{OPENWEATHER_HOST}{OPENWEATHER_PATH}?{query}"


def assert_openweather_url(url: str) -> str:
    parsed = urlparse(url)
    if parsed.scheme != "https" or parsed.hostname != OPENWEATHER_HOST:
        raise WeatherError("Refusing weather request to unexpected host")
    if parsed.path != OPENWEATHER_PATH:
        raise WeatherError("Refusing weather request to unexpected path")
    return url


def format_weather_payload(payload: dict) -> str:
    weather = payload.get("weather") or []
    condition = weather[0].get("description", "") if weather else ""
    main = payload.get("main") or {}
    temp = main.get("temp")
    city = payload.get("name") or ""
    if temp is None:
        return condition or "weather unavailable"
    label = f"{round(temp)}°C"
    if condition:
        label = f"{condition}, {label}"
    if city:
        label = f"{city}: {label}"
    return label


def fetch_weather_summary(city: str, api_key: str) -> str:
    import requests

    url = assert_openweather_url(build_weather_url(city, api_key))
    response = requests.get(url, timeout=10)
    response.raise_for_status()
    return format_weather_payload(response.json())
