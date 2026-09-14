# Python Automation Scripts

Production-oriented Python tools for scraping, desktop assistance, and gamified task tracking.

## What's in this repository

| Tool | Path | Purpose |
| --- | --- | --- |
| Web scraper | `web-scraper/` | Category-aware HTML extraction with SSRF guards, retries, and JSON/JSONL/CSV/Excel export |
| Desktop assistant | `desktop-assistant/` | Claude-powered local assistant with reminders, stats, and notifications |
| To-Dojo | `to-dojo/` | Ranked task manager with streaks, achievements, and a CLI |
| Granola Engineer | `granola-engineer/` | Turn exported Granola meeting notes into action items and To-Dojo tasks |

Python 3.10+ is required. Per-tool details live in each folder's README.

## Security defaults

- Scrape targets must be `http` or `https`. Loopback, link-local, metadata, and private ranges are blocked unless you pass `--allow-private`.
- `--allow-host` optionally pins allowed hostnames.
- Redirects are followed only after the next URL is re-checked.
- Responses are capped (`SCRAPER_MAX_BYTES`, default 5 MB).
- `robots.txt` is respected unless `SCRAPER_RESPECT_ROBOTS=false`.
- The assistant redacts obvious API tokens before sending clipboard text to the model.
- Optional weather briefing calls only `api.openweathermap.org`.
- To-Dojo writes state atomically and quarantines corrupt JSON instead of crashing.

Do not scrape sites you are not allowed to access. Honor terms of service and rate limits.

## Setup

```bash
git clone https://github.com/donny-devops/python-automation-scripts.git
cd python-automation-scripts
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

Tool extras (or the matching `*/requirements.txt`):

```bash
pip install -e ".[scraper]"
pip install -e ".[assistant]"
pip install -e ".[dojo]"
pip install -e ".[granola]"
```

Editable install also provides `web-scraper`, `to-dojo`, and `desktop-assistant` console commands.

Copy the matching `.env.example` to `.env` and fill in values. Never commit secrets.

## Web scraper

```bash
python web-scraper/scraper.py --dry-run --url https://example.com
python web-scraper/scraper.py --category news --url https://example.com --format jsonl --allow-host example.com
```

See [web-scraper/README.md](web-scraper/README.md). Scheduler samples: [examples/cron.example](examples/cron.example), [examples/systemd/](examples/systemd/).

## Desktop assistant

```bash
python desktop-assistant/assistant.py --text
```

See [desktop-assistant/README.md](desktop-assistant/README.md). Host-only (mic/TTS/clipboard); not shipped in Docker.

## To-Dojo

```bash
python to-dojo/to_dojo.py add "Write tests" --priority high
python to-dojo/to_dojo.py complete 1
python to-dojo/to_dojo.py history
```

See [to-dojo/README.md](to-dojo/README.md). Default state file is `~/.to-dojo/dojo_data.json` unless `./dojo_data.json` already exists.

## Granola Engineer

```bash
python granola-engineer/granola_engineer.py list export.json
python granola-engineer/granola_engineer.py to-dojo export.json --data-file dojo.json
```

Reads a local Granola meeting-notes export (JSON), extracts action items, and
optionally creates To-Dojo tasks from them (deduped by title). No network, no
secrets. See [granola-engineer/README.md](granola-engineer/README.md).

## Docker

The image runs the scraper and To-Dojo (no Playwright, no assistant):

```bash
docker build -t python-automation-scripts .
docker run --rm python-automation-scripts web-scraper/scraper.py --help
docker run --rm -v dojo-data:/data python-automation-scripts \
  to-dojo/to_dojo.py --data-file /data/dojo.json list
```

For JS rendering, install Playwright on the host: `playwright install chromium`.

## Development

```bash
pip install -e ".[dev]"
ruff check .
pytest
```

CI runs Ruff, pytest, Bandit, pip-audit, and secret scanning through the AgentOps fleet workflow.

## License

MIT. See `LICENSE` and `SECURITY.md` for disclosure instructions.
