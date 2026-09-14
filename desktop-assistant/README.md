# Desktop assistant

Local Claude-powered assistant with reminders, system stats, and optional voice.

This tool is **not** containerized. It needs a microphone, TTS, and clipboard on the host.

## Install

```bash
pip install -e ".[assistant]"
# or
pip install -r desktop-assistant/requirements.txt
```

Copy `.env.example` to `.env` and set `ANTHROPIC_API_KEY`. Optional: `WEATHER_API_KEY` and `CITY` for an OpenWeather line in the daily briefing (requests go only to `api.openweathermap.org`).

## Usage

```bash
python desktop-assistant/assistant.py --text
python desktop-assistant/assistant.py --notify
```

Voice mode (default when `VOICE_ENABLED=true`) requires the wake word (`WAKE_WORD`, default `aria`) on every spoken utterance. `--text` does not.

Commands: `quit`, `clear`, `stats`.
