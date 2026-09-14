import json
from bs4 import BeautifulSoup

from scraper import (
    EcommerceScraper,
    JobsScraper,
    NewsScraper,
    SocialScraper,
    WeatherScraper,
    _normalize_jobs,
    compute_discount,
    export,
    main,
    run_scrape,
)


ECOMMERCE_HTML = """
<html><body>
  <div class="product-card">
    <h3 class="product-title">Widget Pro</h3>
    <span class="price">$80</span>
    <span class="original-price">$100</span>
    <span class="stock">In stock</span>
    <a href="/p/widget">View</a>
  </div>
</body></html>
"""

NEWS_HTML = """
<html><body>
  <article>
    <h2>City Council Approves Plan</h2>
    <p class="excerpt">Leaders voted to expand the park district after a lengthy debate.</p>
    <span class="author">Ada Lovelace</span>
    <time datetime="2026-09-14">Sep 14</time>
    <a href="/news/plan">Read</a>
  </article>
</body></html>
"""

JOBS_HTML = """
<html><body>
  <div class="job-card">
    <h2 class="job-title">Staff Engineer (Remote)</h2>
    <div class="company">PipeFish Labs</div>
    <div class="location">Remote — US</div>
    <div class="salary">$180k</div>
    <a href="/jobs/1">Apply</a>
  </div>
</body></html>
"""

WEATHER_HTML = """
<html><body>
  <h1 class="location">Miami</h1>
  <div class="condition">Partly cloudy</div>
  <div class="temperature">88°F</div>
  <div class="humidity">70%</div>
</body></html>
"""

SOCIAL_HTML = """
<html><body>
  <article class="post-card">
    <h2 class="title">Best kata for beginners?</h2>
    <p class="body">Looking for a focused drill this week.</p>
    <span class="author">white-belt</span>
    <span class="score">42</span>
    <a href="/t/1">link</a>
  </article>
</body></html>
"""


def test_compute_discount():
    assert compute_discount("$80", "$100") == "20%"
    assert compute_discount("free", "n/a") == ""
    assert compute_discount("$120", "$100") == ""


def test_ecommerce_parser():
    soup = BeautifulSoup(ECOMMERCE_HTML, "lxml")
    items = EcommerceScraper("https://shop.example/catalog").parse(soup)
    assert len(items) == 1
    assert items[0]["name"] == "Widget Pro"
    assert items[0]["discount"] == "20%"
    assert items[0]["product_url"].endswith("/p/widget")


def test_news_parser():
    soup = BeautifulSoup(NEWS_HTML, "lxml")
    items = NewsScraper("https://news.example").parse(soup)
    assert items[0]["headline"].startswith("City Council")
    assert items[0]["author"] == "Ada Lovelace"
    assert items[0]["published_at"] == "2026-09-14"


def test_jobs_remote_flag():
    soup = BeautifulSoup(JOBS_HTML, "lxml")
    items = JobsScraper("https://jobs.example").parse(soup)
    assert items[0]["remote"] is True
    assert items[0]["company"] == "PipeFish Labs"


def test_weather_and_social_parsers():
    weather = WeatherScraper("https://weather.example").parse(
        BeautifulSoup(WEATHER_HTML, "lxml")
    )
    social = SocialScraper("https://forum.example").parse(BeautifulSoup(SOCIAL_HTML, "lxml"))
    assert weather[0]["location"] == "Miami"
    assert social[0]["score"] == "42"


def test_config_normalization_rejects_bad_jobs():
    jobs = _normalize_jobs({"category": "news", "url": "https://news.example"})
    assert jobs[0]["category"] == "news"
    try:
        _normalize_jobs({"url": "https://x.example", "category": "not-a-category"})
        assert False, "expected ValueError"
    except ValueError:
        pass


def test_export_json(tmp_path, monkeypatch):
    monkeypatch.setattr("scraper.OUTPUT_DIR", tmp_path)
    from scraper import ScrapedItem

    items = [
        ScrapedItem(url="https://example.com", category="generic", data={"title": "Hello"})
    ]
    export(items, "json", "generic")
    files = list(tmp_path.glob("generic_*.json"))
    assert len(files) == 1
    payload = json.loads(files[0].read_text(encoding="utf-8"))
    assert payload[0]["title"] == "Hello"


def test_dry_run_blocks_loopback():
    assert main(["--dry-run", "--url", "http://127.0.0.1/"]) == 1


def test_dry_run_allows_private_loopback():
    assert main(["--dry-run", "--allow-private", "--url", "http://127.0.0.1/status"]) == 0


def test_run_scrape_dry_run_skips_network():
    items = run_scrape(
        "generic",
        "http://127.0.0.1/status",
        dry_run=True,
        allow_private=True,
    )
    assert items == []
