# Web scraper

Category-aware HTML extraction with SSRF guards, retries, and file export.

## Install

```bash
pip install -e ".[scraper]"
# or
pip install -r web-scraper/requirements.txt
```

Playwright (optional, JS-rendered pages):

```bash
playwright install chromium
```

Copy `.env.example` to `.env` in this directory or the repo root.

## Usage

```bash
python web-scraper/scraper.py --dry-run --url https://example.com
python web-scraper/scraper.py --category news --url https://example.com --format jsonl
python web-scraper/scraper.py --allow-host example.com --url https://example.com
python web-scraper/scraper.py --config web-scraper/config.example.json --log-level INFO
```

After `pip install -e .`, the same flags work as `web-scraper ...`.

## Security

- Only `http`/`https` URLs.
- Private, loopback, and cloud-metadata hosts are blocked unless `--allow-private`.
- `--allow-host` further restricts the hostname (repeatable).
- Redirects are re-validated. Responses are capped (`SCRAPER_MAX_BYTES`).
- `robots.txt` is respected unless `SCRAPER_RESPECT_ROBOTS=false`.

Do not scrape sites you are not allowed to access.
