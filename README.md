# Python Automation Scripts

Production-oriented Python tools for scraping, desktop assistance, and gamified task tracking.

## What's in this repository

| Tool | Path | Purpose |
| --- | --- | --- |
| Web scraper | `web-scraper/` | Category-aware HTML extraction with SSRF guards, retries, and JSON/CSV/Excel export |
| Desktop assistant | `desktop-assistant/` | Claude-powered local assistant with reminders, stats, and notifications |
| To-Dojo | `to-dojo/` | Ranked task manager with streaks, achievements, and an optional CLI |

Python 3.10+ is required.

## Security defaults

- Scrape targets must be `http` or `https`. Loopback, link-local, metadata, and private ranges are blocked unless you pass `--allow-private`.
- Redirects are followed only after the next URL is re-checked.
- Responses are capped (`SCRAPER_MAX_BYTES`, default 5 MB).
- `robots.txt` is respected unless `SCRAPER_RESPECT_ROBOTS=false`.
- The assistant redacts obvious API tokens before sending clipboard text to the model.
- To-Dojo writes state atomically and quarantines corrupt JSON instead of crashing.

Do not scrape sites you are not allowed to access. Honor terms of service and rate limits.

## Setup

```bash
git clone https://github.com/donny-devops/python-automation-scripts.git
cd python-automation-scripts
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Install extra dependencies only for the tool you are running:

```bash
pip install -r web-scraper/requirements.txt
pip install -r desktop-assistant/requirements.txt
pip install -r to-dojo/requirements.txt
```

Copy the matching `.env.example` to `.env` and fill in values. Never commit secrets.

## Web scraper

```bash
python web-scraper/scraper.py --help
python web-scraper/scraper.py --dry-run --url https://example.com
python web-scraper/scraper.py --category news --url https://example.com --format json
python web-scraper/scraper.py --config web-scraper/config.example.json
```

Categories: `ecommerce`, `news`, `jobs`, `real_estate`, `finance`, `social`, `weather`, `generic`.

Useful flags:

- `--dry-run` — validate the URL and plan the fetch without downloading
- `--js` — render with Playwright
- `--allow-private` — permit intranet/loopback targets
- `--schedule MINUTES` — repeat on an interval

## Desktop assistant

```bash
cp desktop-assistant/.env.example desktop-assistant/.env
python desktop-assistant/assistant.py --text
python desktop-assistant/assistant.py --notify
```

`ANTHROPIC_API_KEY` is required at runtime, not at import. Commands: `quit`, `clear`, `stats`.

## To-Dojo

Interactive:

```bash
python to-dojo/to_dojo.py
```

Non-interactive:

```bash
python to-dojo/to_dojo.py add "Write tests" --priority high
python to-dojo/to_dojo.py list
python to-dojo/to_dojo.py complete 1
python to-dojo/to_dojo.py stats
```

State is stored in `dojo_data.json` (override with `--data-file` or `DOJO_DATA_FILE`). Streaks increase only when you complete a task, not when you open the app.

## Development

```bash
pip install -r requirements.txt
ruff check .
pytest
```

CI runs Ruff, pytest, Bandit, pip-audit, and secret scanning through the AgentOps fleet workflow.

## License

MIT. See `LICENSE` and `SECURITY.md` for disclosure instructions.
