"""
Highly Comprehensive Automated Web Scraper
──────────────────────────────────────────
Categories supported:
  1. E-Commerce      — products, prices, stock, reviews
  2. News / Media    — headlines, articles, authors, dates
  3. Jobs            — listings, companies, salaries, locations
  4. Real Estate     — listings, prices, specs, agents
  5. Social / Forums — posts, threads, scores, authors
  6. Finance         — stock quotes, crypto, exchange rates
  7. Weather         — forecasts, conditions, alerts
  8. Generic         — configurable CSS extraction

Features:
  • Static (requests + BS4) and dynamic (Playwright) rendering modes
  • Rotating user-agents, optional proxy support
  • Retry with exponential backoff and per-domain rate limiting
  • SSRF guards (http/https only; private hosts blocked unless --allow-private)
  • robots.txt respect, response size limits, redirect checks
  • Output: JSON, JSONL, CSV, Excel
  • Structured logging for scheduled runs
  • Scheduled scraping via schedule
  • Rich console progress display

Usage:
  python scraper.py --category ecommerce --url https://example.com/shop
  python scraper.py --category news      --url https://news.example.com
  python scraper.py --category jobs      --url https://jobs.example.com
  python scraper.py --config job.json    # run from config file
  python scraper.py --dry-run --url https://example.com
  python scraper.py --schedule 30        # run every 30 minutes
"""

import os
import re
import sys
import json
import time
import asyncio
import random
import hashlib
import logging
import argparse
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse, urljoin
from urllib.robotparser import RobotFileParser

import requests
from bs4 import BeautifulSoup
from dotenv import load_dotenv
from rich.console import Console
from rich.table import Table
from tenacity import retry, stop_after_attempt, wait_exponential

from safety import (
    UnsafeURLError,
    assert_safe_proxy,
    assert_safe_url,
    max_redirects,
    max_response_bytes,
    resolve_redirect,
)

load_dotenv()

console = Console()
log = logging.getLogger("web_scraper")

# ── Config ────────────────────────────────────────────────────────────────────

DELAY_MIN = float(os.getenv("SCRAPER_DELAY_MIN", 1.0))
DELAY_MAX = float(os.getenv("SCRAPER_DELAY_MAX", 3.0))
MAX_RETRIES = int(os.getenv("SCRAPER_MAX_RETRIES", 3))
OUTPUT_DIR = Path(os.getenv("SCRAPER_OUTPUT_DIR", "./output"))
HEADLESS = os.getenv("SCRAPER_HEADLESS", "true").lower() == "true"
PROXY_URL = os.getenv("PROXY_URL", "")
USER_AGENT = os.getenv("SCRAPER_USER_AGENT", "random")
RESPECT_ROBOTS = os.getenv("SCRAPER_RESPECT_ROBOTS", "true").lower() == "true"

DEFAULT_UA = (
    "Mozilla/5.0 (compatible; PythonAutomationScripts/1.0; +https://github.com/donny-devops/python-automation-scripts)"
)
_SESSION: requests.Session | None = None
_UA = None
_LAST_HIT: dict[str, float] = {}
_ROBOTS_CACHE: dict[str, RobotFileParser | None] = {}


# ── Data Models ───────────────────────────────────────────────────────────────


@dataclass
class ScrapedItem:
    url: str
    category: str
    scraped_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    data: dict = field(default_factory=dict)
    error: str | None = None

    def id(self) -> str:
        return hashlib.md5(f"{self.url}{self.scraped_at}".encode(), usedforsecurity=False).hexdigest()[:12]


# ── HTTP Helpers ──────────────────────────────────────────────────────────────


def configure_logging(level: str) -> None:
    resolved = getattr(logging, level.upper(), None)
    if not isinstance(resolved, int):
        resolved = logging.INFO
    logging.basicConfig(
        level=resolved,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )


def _user_agent() -> str:
    global _UA
    if USER_AGENT == "default":
        return DEFAULT_UA
    if USER_AGENT and USER_AGENT != "random":
        return USER_AGENT
    try:
        from fake_useragent import UserAgent

        if _UA is None:
            _UA = UserAgent()
        return _UA.random
    except Exception:
        return DEFAULT_UA


def get_headers() -> dict:
    return {
        "User-Agent": _user_agent(),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.5",
        "Accept-Encoding": "gzip, deflate, br",
        "DNT": "1",
        "Connection": "keep-alive",
        "Upgrade-Insecure-Requests": "1",
    }


def get_session() -> requests.Session:
    global _SESSION
    if _SESSION is None:
        _SESSION = requests.Session()
        adapter = requests.adapters.HTTPAdapter(pool_connections=8, pool_maxsize=8)
        _SESSION.mount("http://", adapter)
        _SESSION.mount("https://", adapter)
    return _SESSION


def _proxies() -> dict | None:
    proxy = assert_safe_proxy(PROXY_URL)
    if not proxy:
        return None
    return {"http": proxy, "https": proxy}


def polite_delay(url: str = "") -> None:
    domain = urlparse(url).netloc if url else ""
    elapsed = time.monotonic() - _LAST_HIT.get(domain, 0.0)
    wait_for = random.uniform(DELAY_MIN, DELAY_MAX) - elapsed
    if wait_for > 0:
        time.sleep(wait_for)
    _LAST_HIT[domain] = time.monotonic()


def allowed_by_robots(url: str, *, allow_private: bool = False) -> bool:
    if not RESPECT_ROBOTS:
        return True
    parsed = urlparse(url)
    robots_url = f"{parsed.scheme}://{parsed.netloc}/robots.txt"
    if robots_url not in _ROBOTS_CACHE:
        rp = RobotFileParser()
        rp.set_url(robots_url)
        try:
            assert_safe_url(robots_url, allow_private=allow_private)
            polite_delay(robots_url)
            resp = get_session().get(
                robots_url,
                headers=get_headers(),
                proxies=_proxies(),
                timeout=10,
                allow_redirects=False,
                stream=True,
            )
            if resp.status_code >= 400:
                _ROBOTS_CACHE[robots_url] = None
                return True
            rp.parse(_read_limited(resp).splitlines())
            _ROBOTS_CACHE[robots_url] = rp
        except Exception:
            _ROBOTS_CACHE[robots_url] = None
            return True
    rp = _ROBOTS_CACHE[robots_url]
    if rp is None:
        return True
    return rp.can_fetch(_user_agent(), url)


def _read_limited(resp: requests.Response) -> str:
    limit = max_response_bytes()
    chunks: list[bytes] = []
    total = 0
    for chunk in resp.iter_content(chunk_size=8192):
        if not chunk:
            continue
        total += len(chunk)
        if total > limit:
            resp.close()
            raise ValueError(f"Response exceeds {limit} byte limit")
        chunks.append(chunk)
    encoding = resp.encoding or "utf-8"
    return b"".join(chunks).decode(encoding, errors="replace")


def compute_discount(price: str, original: str) -> str:
    try:
        p = float(re.sub(r"[^\d.]", "", price or ""))
        op = float(re.sub(r"[^\d.]", "", original or ""))
        if op > p > 0:
            return f"{round((op - p) / op * 100)}%"
    except (TypeError, ValueError):
        return ""
    return ""


@retry(
    stop=stop_after_attempt(MAX_RETRIES),
    wait=wait_exponential(multiplier=1, min=2, max=10),
    reraise=True,
)
def fetch_static(
    url: str, *, allow_private: bool = False, allow_hosts: list[str] | None = None
) -> BeautifulSoup:
    current = assert_safe_url(url, allow_private=allow_private, allow_hosts=allow_hosts)
    session = get_session()
    for _ in range(max_redirects() + 1):
        polite_delay(current)
        resp = session.get(
            current,
            headers=get_headers(),
            proxies=_proxies(),
            timeout=15,
            allow_redirects=False,
            stream=True,
        )
        if resp.is_redirect or resp.status_code in {301, 302, 303, 307, 308}:
            location = resp.headers.get("Location", "")
            resp.close()
            current = resolve_redirect(
                current, location, allow_private=allow_private, allow_hosts=allow_hosts
            )
            continue
        resp.raise_for_status()
        html = _read_limited(resp)
        return BeautifulSoup(html, "lxml")
    raise ValueError("Too many redirects")


async def fetch_dynamic(
    url: str, *, allow_private: bool = False, allow_hosts: list[str] | None = None
) -> BeautifulSoup:
    from playwright.async_api import async_playwright

    target = assert_safe_url(url, allow_private=allow_private, allow_hosts=allow_hosts)
    polite_delay(target)
    launch_kwargs: dict = {"headless": HEADLESS}
    proxy = assert_safe_proxy(PROXY_URL)
    if proxy:
        launch_kwargs["proxy"] = {"server": proxy}

    async with async_playwright() as p:
        browser = await p.chromium.launch(**launch_kwargs)
        try:
            page = await browser.new_page(extra_http_headers=get_headers())
            await page.goto(target, wait_until="networkidle", timeout=30000)
            await page.wait_for_timeout(2000)
            html = await page.content()
        finally:
            await browser.close()
    return BeautifulSoup(html, "lxml")


def safe_text(el) -> str:
    return el.get_text(strip=True) if el else ""


def safe_attr(el, attr: str) -> str:
    return el.get(attr, "").strip() if el else ""


# ── Base Scraper ──────────────────────────────────────────────────────────────


class BaseScraper(ABC):
    category: str = "generic"
    requires_js: bool = False

    def __init__(
        self,
        url: str,
        *,
        js: bool = False,
        allow_private: bool = False,
        dry_run: bool = False,
        allow_hosts: list[str] | None = None,
    ):
        self.url = url
        self.base = f"{urlparse(url).scheme}://{urlparse(url).netloc}"
        self.force_js = js
        self.allow_private = allow_private
        self.dry_run = dry_run
        self.allow_hosts = allow_hosts

    def get_soup(self) -> BeautifulSoup:
        use_js = self.force_js or self.requires_js
        if use_js:
            return asyncio.run(
                fetch_dynamic(
                    self.url,
                    allow_private=self.allow_private,
                    allow_hosts=self.allow_hosts,
                )
            )
        return fetch_static(
            self.url, allow_private=self.allow_private, allow_hosts=self.allow_hosts
        )

    @abstractmethod
    def parse(self, soup: BeautifulSoup) -> list[dict]:
        """Return list of extracted item dicts."""
        ...

    def scrape(self) -> list[ScrapedItem]:
        items: list[ScrapedItem] = []
        try:
            assert_safe_url(
                self.url, allow_private=self.allow_private, allow_hosts=self.allow_hosts
            )
            if self.dry_run:
                log.info("dry-run [%s] would fetch %s", self.category, self.url)
                console.print(
                    f"[yellow]dry-run[/] [{self.category}] would fetch {self.url}"
                )
                return items
            if not allowed_by_robots(self.url, allow_private=self.allow_private):
                raise UnsafeURLError(f"robots.txt disallows fetching {self.url}")
            soup = self.get_soup()
            records = self.parse(soup)
            for r in records:
                items.append(ScrapedItem(url=self.url, category=self.category, data=r))
            log.info("[%s] %s items from %s", self.category, len(items), self.url)
            console.print(
                f"[green]✓[/] [{self.category}] {len(items)} items from {self.url}"
            )
        except UnsafeURLError:
            raise
        except Exception as e:
            log.warning("[%s] %s — %s", self.category, self.url, e)
            console.print(f"[red]✗[/] [{self.category}] {self.url} — {e}")
            items.append(
                ScrapedItem(url=self.url, category=self.category, error=str(e))
            )
        return items


# ── Category Scrapers ─────────────────────────────────────────────────────────


class EcommerceScraper(BaseScraper):
    """
    Category: E-Commerce
    Extracts: product name, price, original price, discount %, stock status,
              rating, review count, SKU, image URL, product URL.
    Works with common Shopify / WooCommerce / generic product page patterns.
    """

    category = "ecommerce"

    def parse(self, soup: BeautifulSoup) -> list[dict]:
        items = []
        # Try common product card selectors
        cards = (
            soup.select("[class*='product-card']")
            or soup.select("[class*='product-item']")
            or soup.select("[class*='ProductCard']")
            or soup.select("article[class*='product']")
            or soup.select("li[class*='product']")
        )
        if not cards:
            # Single product page fallback
            cards = [soup]

        for card in cards:
            name = safe_text(
                card.select_one(
                    "[class*='product-title'], [class*='product-name'], h2, h3"
                )
            )
            price = safe_text(
                card.select_one(
                    "[class*='price']:not([class*='original']):not([class*='was'])"
                )
            )
            orig = safe_text(
                card.select_one(
                    "[class*='original-price'], [class*='was-price'], [class*='compare']"
                )
            )
            stock = safe_text(
                card.select_one(
                    "[class*='stock'], [class*='availability'], [class*='inventory']"
                )
            )
            rating = safe_text(
                card.select_one(
                    "[class*='rating'], [class*='stars'], [aria-label*='rating']"
                )
            )
            reviews = safe_text(
                card.select_one("[class*='review-count'], [class*='reviews']")
            )
            img_el = card.select_one("img[src], img[data-src], img[data-lazy-src]")
            img_url = safe_attr(img_el, "src") or safe_attr(img_el, "data-src") or ""
            link_el = card.select_one("a[href]")
            link = (
                urljoin(self.base, safe_attr(link_el, "href")) if link_el else self.url
            )

            if not name:
                continue

            discount = compute_discount(price, orig)

            items.append(
                {
                    "name": name,
                    "price": price,
                    "original_price": orig,
                    "discount": discount,
                    "stock_status": stock,
                    "rating": rating,
                    "review_count": reviews,
                    "image_url": img_url,
                    "product_url": link,
                }
            )
        return items


class NewsScraper(BaseScraper):
    """
    Category: News / Media
    Extracts: headline, summary, author, published date, category/tag,
              image URL, article URL, reading time estimate.
    """

    category = "news"

    def parse(self, soup: BeautifulSoup) -> list[dict]:
        items = []
        cards = (
            soup.select("article")
            or soup.select("[class*='article-card']")
            or soup.select("[class*='news-item']")
            or soup.select("[class*='story']")
        )
        for card in cards:
            headline = safe_text(card.select_one("h1, h2, h3, h4"))
            summary = safe_text(
                card.select_one(
                    "p, [class*='excerpt'], [class*='summary'], [class*='description']"
                )
            )
            author = safe_text(
                card.select_one(
                    "[class*='author'], [rel='author'], [itemprop='author']"
                )
            )
            date_el = card.select_one(
                "time, [class*='date'], [class*='time'], [datetime]"
            )
            pub_date = safe_attr(date_el, "datetime") or safe_text(date_el)
            tag = safe_text(
                card.select_one(
                    "[class*='tag'], [class*='category'], [class*='section']"
                )
            )
            img_el = card.select_one("img")
            img_url = safe_attr(img_el, "src") or safe_attr(img_el, "data-src") or ""
            link_el = card.select_one("a[href]")
            link = urljoin(self.base, safe_attr(link_el, "href")) if link_el else ""
            word_count = len(summary.split())
            read_time = max(1, round(word_count / 200))

            if not headline:
                continue
            items.append(
                {
                    "headline": headline,
                    "summary": summary[:300],
                    "author": author,
                    "published_at": pub_date,
                    "category": tag,
                    "image_url": img_url,
                    "article_url": link,
                    "reading_time_min": read_time,
                }
            )
        return items


class JobsScraper(BaseScraper):
    """
    Category: Jobs
    Extracts: title, company, location, salary range, job type,
              remote flag, posted date, skills/tags, apply URL.
    """

    category = "jobs"

    REMOTE_KEYWORDS = {"remote", "work from home", "wfh", "distributed", "anywhere"}

    def parse(self, soup: BeautifulSoup) -> list[dict]:
        items = []
        cards = (
            soup.select("[class*='job-card']")
            or soup.select("[class*='job-listing']")
            or soup.select("[class*='JobCard']")
            or soup.select("li[class*='job']")
            or soup.select("[data-testid*='job']")
        )
        for card in cards:
            title = safe_text(
                card.select_one("h2, h3, [class*='job-title'], [class*='title']")
            )
            company = safe_text(
                card.select_one("[class*='company'], [class*='employer']")
            )
            location = safe_text(
                card.select_one("[class*='location'], [class*='city']")
            )
            salary = safe_text(
                card.select_one(
                    "[class*='salary'], [class*='pay'], [class*='compensation']"
                )
            )
            job_type = safe_text(
                card.select_one("[class*='type'], [class*='employment']")
            )
            date_el = card.select_one("time, [class*='posted'], [class*='date']")
            posted = safe_attr(date_el, "datetime") or safe_text(date_el)
            tags = [
                safe_text(t)
                for t in card.select(
                    "[class*='tag'], [class*='skill'], [class*='badge']"
                )
            ]
            link_el = card.select_one("a[href]")
            link = urljoin(self.base, safe_attr(link_el, "href")) if link_el else ""
            haystack = f"{location} {title} {job_type}".lower()
            is_remote = any(kw in haystack for kw in self.REMOTE_KEYWORDS)

            if not title:
                continue
            items.append(
                {
                    "title": title,
                    "company": company,
                    "location": location,
                    "salary": salary,
                    "job_type": job_type,
                    "remote": is_remote,
                    "posted_at": posted,
                    "skills": tags[:10],
                    "apply_url": link,
                }
            )
        return items


class RealEstateScraper(BaseScraper):
    """
    Category: Real Estate
    Extracts: address, price, beds, baths, sqft, lot size, property type,
              year built, days on market, agent, listing URL, image URL.
    """

    category = "real_estate"

    def parse(self, soup: BeautifulSoup) -> list[dict]:
        items = []
        cards = (
            soup.select("[class*='listing-card']")
            or soup.select("[class*='property-card']")
            or soup.select("[class*='HomeCard']")
            or soup.select("[class*='result-card']")
        )
        for card in cards:
            address = safe_text(
                card.select_one("[class*='address'], [itemprop='streetAddress']")
            )
            price = safe_text(card.select_one("[class*='price'], [class*='Price']"))
            beds = safe_text(card.select_one("[class*='beds'], [class*='bedroom']"))
            baths = safe_text(card.select_one("[class*='baths'], [class*='bathroom']"))
            sqft = safe_text(
                card.select_one("[class*='sqft'], [class*='area'], [class*='size']")
            )
            prop_type = safe_text(
                card.select_one("[class*='type'], [class*='property-type']")
            )
            agent = safe_text(
                card.select_one(
                    "[class*='agent'], [class*='broker'], [class*='realtor']"
                )
            )
            days = safe_text(
                card.select_one("[class*='days'], [class*='dom'], [class*='market']")
            )
            img_el = card.select_one("img")
            img_url = safe_attr(img_el, "src") or safe_attr(img_el, "data-src") or ""
            link_el = card.select_one("a[href]")
            link = urljoin(self.base, safe_attr(link_el, "href")) if link_el else ""

            if not address and not price:
                continue
            items.append(
                {
                    "address": address,
                    "price": price,
                    "bedrooms": beds,
                    "bathrooms": baths,
                    "sqft": sqft,
                    "property_type": prop_type,
                    "agent": agent,
                    "days_on_market": days,
                    "image_url": img_url,
                    "listing_url": link,
                }
            )
        return items


class FinanceScraper(BaseScraper):
    """
    Category: Finance
    Extracts: symbol, name, price, change, change %, volume, market cap,
              52w high/low, P/E ratio.
    Targets generic finance table pages.
    """

    category = "finance"

    def parse(self, soup: BeautifulSoup) -> list[dict]:
        items = []
        rows = (
            soup.select("table tr")
            or soup.select("[class*='quote-row']")
            or soup.select("[class*='ticker-row']")
        )
        for row in rows[1:]:  # skip header
            cells = [safe_text(td) for td in row.select("td")]
            if len(cells) < 3:
                continue
            items.append(
                {
                    "symbol": cells[0] if len(cells) > 0 else "",
                    "name": cells[1] if len(cells) > 1 else "",
                    "price": cells[2] if len(cells) > 2 else "",
                    "change": cells[3] if len(cells) > 3 else "",
                    "change_pct": cells[4] if len(cells) > 4 else "",
                    "volume": cells[5] if len(cells) > 5 else "",
                    "market_cap": cells[6] if len(cells) > 6 else "",
                }
            )
        return items


class SocialScraper(BaseScraper):
    """
    Category: Social / Forums
    Extracts: author, title/body, score, comment count, posted date, permalink.
    """

    category = "social"

    def parse(self, soup: BeautifulSoup) -> list[dict]:
        items = []
        cards = (
            soup.select("[class*='post-card']")
            or soup.select("[class*='thread']")
            or soup.select("article")
            or soup.select("[data-testid*='post']")
        )
        for card in cards:
            title = safe_text(card.select_one("h1, h2, h3, [class*='title']"))
            body = safe_text(
                card.select_one("[class*='body'], [class*='content'], p")
            )
            author = safe_text(
                card.select_one("[class*='author'], [class*='user'], [rel='author']")
            )
            score = safe_text(
                card.select_one("[class*='score'], [class*='upvote'], [class*='votes']")
            )
            comments = safe_text(
                card.select_one("[class*='comment'], [class*='replies']")
            )
            date_el = card.select_one("time, [class*='date']")
            posted = safe_attr(date_el, "datetime") or safe_text(date_el)
            link_el = card.select_one("a[href]")
            link = urljoin(self.base, safe_attr(link_el, "href")) if link_el else ""
            if not title and not body:
                continue
            items.append(
                {
                    "title": title,
                    "body": body[:400],
                    "author": author,
                    "score": score,
                    "comments": comments,
                    "posted_at": posted,
                    "permalink": link,
                }
            )
        return items


class WeatherScraper(BaseScraper):
    """
    Category: Weather
    Extracts: location, condition, temperature, humidity, wind, alert text.
    """

    category = "weather"

    def parse(self, soup: BeautifulSoup) -> list[dict]:
        location = safe_text(
            soup.select_one("[class*='location'], [class*='city'], h1")
        )
        condition = safe_text(
            soup.select_one("[class*='condition'], [class*='weather-desc'], [class*='summary']")
        )
        temp = safe_text(
            soup.select_one("[class*='temp'], [class*='temperature'], [data-testid*='temp']")
        )
        humidity = safe_text(soup.select_one("[class*='humidity']"))
        wind = safe_text(soup.select_one("[class*='wind']"))
        alert = safe_text(soup.select_one("[class*='alert'], [class*='warning']"))
        if not any((location, condition, temp)):
            return []
        return [
            {
                "location": location,
                "condition": condition,
                "temperature": temp,
                "humidity": humidity,
                "wind": wind,
                "alert": alert,
            }
        ]


class GenericScraper(BaseScraper):
    """
    Category: Generic / Custom
    Extracts all headings, links, paragraphs, images, and meta tags.
    Use as a fallback or starting point for custom extraction.
    """

    category = "generic"

    def __init__(
        self,
        url: str,
        selectors: dict | None = None,
        *,
        js: bool = False,
        allow_private: bool = False,
        dry_run: bool = False,
        allow_hosts: list[str] | None = None,
    ):
        super().__init__(
            url,
            js=js,
            allow_private=allow_private,
            dry_run=dry_run,
            allow_hosts=allow_hosts,
        )
        self.selectors = selectors or {}

    def parse(self, soup: BeautifulSoup) -> list[dict]:
        # Custom selectors if provided
        if self.selectors:
            result = {}
            for key, sel in self.selectors.items():
                els = soup.select(sel)
                result[key] = (
                    [safe_text(el) for el in els]
                    if len(els) > 1
                    else safe_text(els[0])
                    if els
                    else ""
                )
            return [result]

        # Generic extraction
        meta = {
            m.get("name", m.get("property", "")): m.get("content", "")
            for m in soup.select("meta[content]")
            if m.get("name") or m.get("property")
        }
        return [
            {
                "title": safe_text(soup.select_one("title")),
                "description": meta.get("description", meta.get("og:description", "")),
                "h1": [safe_text(h) for h in soup.select("h1")],
                "h2": [safe_text(h) for h in soup.select("h2")][:10],
                "paragraphs": [
                    safe_text(p) for p in soup.select("p") if len(safe_text(p)) > 50
                ][:20],
                "links": [
                    {
                        "text": safe_text(a),
                        "href": urljoin(self.base, safe_attr(a, "href")),
                    }
                    for a in soup.select("a[href]")
                    if safe_attr(a, "href").startswith("http")
                ][:30],
                "images": [safe_attr(img, "src") for img in soup.select("img[src]")][
                    :15
                ],
                "meta": {k: v for k, v in meta.items() if k},
            }
        ]


# ── Registry ──────────────────────────────────────────────────────────────────

SCRAPERS: dict[str, type[BaseScraper]] = {
    "ecommerce": EcommerceScraper,
    "news": NewsScraper,
    "jobs": JobsScraper,
    "real_estate": RealEstateScraper,
    "finance": FinanceScraper,
    "social": SocialScraper,
    "weather": WeatherScraper,
    "generic": GenericScraper,
}


# ── Output / Export ───────────────────────────────────────────────────────────


def export(items: list[ScrapedItem], fmt: str, category: str):
    if not items:
        return
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    base = OUTPUT_DIR / f"{category}_{ts}"
    rows = [
        {
            "id": i.id(),
            "url": i.url,
            "scraped_at": i.scraped_at,
            "error": i.error,
            **i.data,
        }
        for i in items
    ]

    if fmt in ("json", "all"):
        path = base.with_suffix(".json")
        path.write_text(json.dumps(rows, indent=2, ensure_ascii=False), encoding="utf-8")
        console.print(f"[cyan]→ JSON:[/] {path}")
        log.info("wrote %s", path)

    if fmt in ("jsonl", "all"):
        path = base.with_suffix(".jsonl")
        lines = [json.dumps(row, ensure_ascii=False) for row in rows]
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        console.print(f"[cyan]→ JSONL:[/] {path}")
        log.info("wrote %s", path)

    if fmt in ("csv", "excel", "all"):
        import pandas as pd

        frame = pd.DataFrame(rows)
        if fmt in ("csv", "all"):
            path = base.with_suffix(".csv")
            frame.to_csv(path, index=False)
            console.print(f"[cyan]→ CSV:[/] {path}")
        if fmt in ("excel", "all"):
            path = base.with_suffix(".xlsx")
            frame.to_excel(path, index=False)
            console.print(f"[cyan]→ Excel:[/] {path}")


def print_table(items: list[ScrapedItem]):
    if not items:
        return
    t = Table(title=f"{items[0].category.upper()} Results", show_lines=True)
    sample = {k: v for k, v in items[0].data.items() if not isinstance(v, list)}
    for col in list(sample.keys())[:6]:
        t.add_column(col, max_width=30)
    for item in items[:20]:
        row = [str(item.data.get(k, ""))[:30] for k in list(sample.keys())[:6]]
        t.add_row(*row)
    console.print(t)


# ── Runner ────────────────────────────────────────────────────────────────────


def run_scrape(
    category: str,
    url: str,
    fmt: str = "json",
    *,
    js: bool = False,
    allow_private: bool = False,
    dry_run: bool = False,
    selectors: dict | None = None,
    allow_hosts: list[str] | None = None,
):
    ScraperClass = SCRAPERS.get(category, GenericScraper)
    kwargs = {
        "js": js,
        "allow_private": allow_private,
        "dry_run": dry_run,
        "allow_hosts": allow_hosts,
    }
    if ScraperClass is GenericScraper:
        scraper = GenericScraper(url, selectors=selectors, **kwargs)
    else:
        scraper = ScraperClass(url, **kwargs)
    items = scraper.scrape()
    if not dry_run:
        print_table(items)
        export(items, fmt, category)
    return items


def _normalize_jobs(config) -> list[dict]:
    jobs = config if isinstance(config, list) else [config]
    normalized = []
    for idx, job in enumerate(jobs, start=1):
        if not isinstance(job, dict):
            raise ValueError(f"Config job #{idx} must be an object")
        url = job.get("url")
        if not url or not isinstance(url, str):
            raise ValueError(f"Config job #{idx} is missing a string 'url'")
        category = job.get("category", "generic")
        if category not in SCRAPERS:
            raise ValueError(f"Config job #{idx} has unknown category {category!r}")
        selectors = job.get("selectors")
        if selectors is not None and not isinstance(selectors, dict):
            raise ValueError(f"Config job #{idx} selectors must be an object")
        normalized.append(
            {"category": category, "url": url.strip(), "selectors": selectors}
        )
    if not normalized:
        raise ValueError("Config did not contain any jobs")
    return normalized


def run_from_config(
    config_path: str,
    fmt: str = "json",
    *,
    js: bool = False,
    allow_private: bool = False,
    dry_run: bool = False,
    allow_hosts: list[str] | None = None,
):
    path = Path(config_path)
    if not path.is_file():
        raise FileNotFoundError(f"Config file not found: {config_path}")
    config = json.loads(path.read_text(encoding="utf-8"))
    for job in _normalize_jobs(config):
        run_scrape(
            job["category"],
            job["url"],
            fmt,
            js=js,
            allow_private=allow_private,
            dry_run=dry_run,
            selectors=job["selectors"],
            allow_hosts=allow_hosts,
        )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Automated Web Scraper")
    parser.add_argument("--category", choices=list(SCRAPERS.keys()), default="generic")
    parser.add_argument("--url", type=str, help="Target URL")
    parser.add_argument("--config", type=str, help="Path to JSON config file")
    parser.add_argument(
        "--format", choices=["json", "jsonl", "csv", "excel", "all"], default="json"
    )
    parser.add_argument(
        "--schedule", type=int, metavar="MINUTES", help="Repeat every N minutes"
    )
    parser.add_argument(
        "--js", action="store_true", help="Force Playwright rendering"
    )
    parser.add_argument(
        "--allow-private",
        action="store_true",
        help="Allow private/loopback scrape targets (off by default)",
    )
    parser.add_argument(
        "--allow-host",
        action="append",
        default=[],
        metavar="HOST",
        help="Restrict fetches to this hostname (repeatable)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate inputs and show planned fetches without downloading",
    )
    parser.add_argument(
        "--log-level",
        default=os.getenv("LOG_LEVEL", "INFO"),
        help="Logging level (default INFO, or LOG_LEVEL)",
    )
    args = parser.parse_args(argv)
    configure_logging(args.log_level)
    allow_hosts = args.allow_host or None

    def job():
        if args.config:
            run_from_config(
                args.config,
                args.format,
                js=args.js,
                allow_private=args.allow_private,
                dry_run=args.dry_run,
                allow_hosts=allow_hosts,
            )
        elif args.url:
            run_scrape(
                args.category,
                args.url,
                args.format,
                js=args.js,
                allow_private=args.allow_private,
                dry_run=args.dry_run,
                allow_hosts=allow_hosts,
            )
        else:
            parser.print_help()
            raise SystemExit(1)

    try:
        if args.schedule:
            import schedule

            if args.schedule < 1:
                raise ValueError("Schedule interval must be at least 1 minute")
            console.print(f"[yellow]Scheduled:[/] running every {args.schedule} minutes")
            schedule.every(args.schedule).minutes.do(job)
            job()
            while True:
                schedule.run_pending()
                time.sleep(30)
        else:
            job()
    except (UnsafeURLError, ValueError, FileNotFoundError, json.JSONDecodeError) as exc:
        console.print(f"[red]{exc}[/]")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
