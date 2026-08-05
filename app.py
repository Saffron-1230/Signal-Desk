from __future__ import annotations

import atexit
import calendar
import json
import logging
import os
import re
import sqlite3
import threading
import time
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from urllib.parse import urljoin, urlparse
from urllib.robotparser import RobotFileParser

import feedparser
import requests
from apscheduler.schedulers.background import BackgroundScheduler
from bs4 import BeautifulSoup
from flask import Flask, jsonify, render_template, request

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
DB_PATH = DATA_DIR / "articles.db"
LOG_PATH = DATA_DIR / "refresh.log"
USER_AGENT = "MarketingNewsDesk/1.0 (+local personal reader; respectful polling)"
REQUEST_TIMEOUT = 20
MAX_ITEMS_PER_SOURCE = 100

SOURCES = {
    "ahrefs": {
        "name": "Ahrefs Blog", "short": "AH", "site": "https://ahrefs.com/blog/",
        "feeds": ["https://ahrefs.com/blog/feed/"],
        "hosts": ["ahrefs.com", "www.ahrefs.com"],
        "archive_pages": ["https://ahrefs.com/blog/archive/"] + [
            f"https://ahrefs.com/blog/archive/page/{page}/" for page in range(2, 21)
        ],
        "archive_listing_selector": "h3 a[href]",
        "archive_container_class": "post-header",
        "archive_titles_canonical": True,
        "color": "#ff6b35",
    },
    "search-engine-land": {
        "name": "Search Engine Land", "short": "SL", "site": "https://searchengineland.com/",
        "feeds": [
            "https://searchengineland.com/feed",
            "https://news.google.com/rss/search?q=site%3Asearchengineland.com%20when%3A30d&hl=en-US&gl=US&ceid=US%3Aen",
        ],
        "title_suffix": " - Search Engine Land",
        "color": "#18a66a",
    },
    "search-engine-journal": {
        "name": "Search Engine Journal", "short": "SJ", "site": "https://www.searchenginejournal.com/",
        "feeds": ["https://www.searchenginejournal.com/feed/"],
        "hosts": ["searchenginejournal.com", "www.searchenginejournal.com"],
        "archive_pages": [
            f"https://www.searchenginejournal.com/page/{page}/" for page in range(2, 13)
        ],
        "archive_titles_canonical": True,
        "color": "#2458d3",
    },
    "semrush": {
        "name": "Semrush Blog", "short": "SE", "site": "https://www.semrush.com/blog/",
        "feeds": ["https://www.semrush.com/blog/feed/", "https://en.semrush.com/blog/feed/"],
        "hosts": ["semrush.com", "www.semrush.com", "en.semrush.com"],
        "include_paths": ["/blog/"],
        "archive_pages": [
            f"https://www.semrush.com/blog/?page={page}" for page in range(2, 13)
        ],
        "archive_titles_canonical": True,
        "color": "#8b5cf6",
    },
    "factors-ai": {
        "name": "Factors.ai Blog", "short": "FA", "site": "https://www.factors.ai/blog",
        "feeds": [], "hosts": ["factors.ai", "www.factors.ai"],
        "include_paths": ["/blog/"], "listing_selector": "main .w-dyn-item > a[href]",
        "title_selector": "h2, h3", "excerpt_selector": "p",
        "listing_container_self": True,
        "color": "#6757d9",
    },
    "webfx": {
        "name": "WebFX Blog", "short": "WF", "site": "https://www.webfx.com/blog/",
        "feeds": ["https://www.webfx.com/blog/feed/"],
        "hosts": ["webfx.com", "www.webfx.com"], "include_paths": ["/blog/"],
        "archive_listing_selector": "a.blog-posts-list-item[href]",
        "archive_container_class": "blog-posts-list-item",
        "archive_title_selector": ".title",
        "archive_excerpt_selector": ".content p",
        "archive_titles_canonical": True,
        "color": "#178bd4",
    },
    "google-ads": {
        "name": "Google Ads Blog", "short": "GA",
        "site": "https://blog.google/innovation-and-ai/technology/ads/",
        "feeds": ["https://blog.google/innovation-and-ai/technology/ads/rss/"],
        "hosts": ["blog.google"], "color": "#4285f4",
    },
    "google-developers": {
        "name": "Google Developers Blog", "short": "GD", "site": "https://developers.googleblog.com/",
        "feeds": ["https://developers.googleblog.com/rss/"],
        "hosts": ["developers.googleblog.com"], "color": "#34a853",
    },
    "google-blog": {
        "name": "Google Blog", "short": "GO", "site": "https://blog.google/",
        "feeds": ["https://blog.google/rss/"], "hosts": ["blog.google"],
        "exclude_paths": [
            "/products/ads-commerce/",
            "/innovation-and-ai/technology/ads/",
            "/products-and-platforms/products/ads/",
        ],
        "color": "#ea4335",
    },
}

DATA_DIR.mkdir(exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
    handlers=[logging.FileHandler(LOG_PATH, encoding="utf-8"), logging.StreamHandler()],
)
log = logging.getLogger("newsdesk")
app = Flask(__name__)
app.config["SEND_FILE_MAX_AGE_DEFAULT"] = 0
refresh_lock = threading.Lock()
scheduler = BackgroundScheduler(timezone=None)
robots_cache: dict[str, RobotFileParser] = {}


@app.after_request
def prevent_stale_dashboard_assets(response):
    if request.path == "/" or request.path.startswith("/static/"):
        response.headers["Cache-Control"] = "no-store, max-age=0"
    return response


def db() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, timeout=20)
    conn.row_factory = sqlite3.Row
    return conn


def is_article_url(url: str) -> bool:
    path = urlparse(url).path.lower()
    excluded = ("/category/", "/tag/", "/author/", "/privacy-policy", "/about/", "/contact/")
    return url.startswith(("http://", "https://")) and not any(part in path for part in excluded)


def source_allows_url(url: str, config: dict) -> bool:
    if not is_article_url(url):
        return False
    parsed = urlparse(url)
    host = parsed.netloc.lower().split(":", 1)[0]
    path = parsed.path.lower()
    allowed_hosts = {value.lower() for value in config.get("hosts", [])}
    include_paths = tuple(value.lower() for value in config.get("include_paths", []))
    exclude_paths = tuple(value.lower() for value in config.get("exclude_paths", []))
    if allowed_hosts and host not in allowed_hosts:
        return False
    if include_paths and not any(value in path for value in include_paths):
        return False
    return not any(value in path for value in exclude_paths)


def filter_source_articles(articles: list[dict], config: dict) -> list[dict]:
    filtered = []
    title_suffix = config.get("title_suffix", "")
    for article in articles:
        if not source_allows_url(article.get("url", ""), config):
            continue
        if title_suffix and article["title"].endswith(title_suffix):
            article["title"] = article["title"][: -len(title_suffix)].rstrip()
        filtered.append(article)
    return filtered


def normalized_title_key(value: str) -> str:
    return re.sub(r"[^\w]+", " ", value.casefold()).strip()


def init_db() -> None:
    with db() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS articles (
                id INTEGER PRIMARY KEY, source_id TEXT NOT NULL, title TEXT NOT NULL,
                url TEXT NOT NULL UNIQUE, published_at TEXT, excerpt TEXT NOT NULL DEFAULT '',
                fetched_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_articles_source_date
                ON articles(source_id, published_at DESC);
            CREATE TABLE IF NOT EXISTS runs (
                id INTEGER PRIMARY KEY, started_at TEXT NOT NULL, finished_at TEXT,
                trigger TEXT NOT NULL, status TEXT NOT NULL, details TEXT
            );
            CREATE TABLE IF NOT EXISTS metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL);
        """)
        columns = {row["name"] for row in conn.execute("PRAGMA table_info(articles)")}
        if "metadata_checked_at" not in columns:
            conn.execute("ALTER TABLE articles ADD COLUMN metadata_checked_at TEXT")
        if "title_checked_at" not in columns:
            conn.execute("ALTER TABLE articles ADD COLUMN title_checked_at TEXT")
        invalid_ids = [row["id"] for row in conn.execute("SELECT id,url FROM articles") if not is_article_url(row["url"])]
        if invalid_ids:
            conn.executemany("DELETE FROM articles WHERE id=?", [(article_id,) for article_id in invalid_ids])
            log.info("removed non-article records | count=%d", len(invalid_ids))


def clean_html(value: str | None, limit: int = 280) -> str:
    raw = value or ""
    text = BeautifulSoup(raw, "html.parser").get_text(" ", strip=True) if "<" in raw else raw
    text = " ".join(text.split())
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def normalize_date(entry: dict) -> str | None:
    stamp = entry.get("published_parsed") or entry.get("updated_parsed")
    if stamp:
        return datetime.fromtimestamp(calendar.timegm(stamp), timezone.utc).isoformat()
    raw = entry.get("published") or entry.get("updated")
    if raw:
        try:
            value = datetime.fromisoformat(raw.replace("Z", "+00:00"))
            if value.tzinfo is None:
                value = value.replace(tzinfo=timezone.utc)
            return value.astimezone(timezone.utc).isoformat()
        except ValueError:
            pass
    return None


def normalize_raw_date(raw: str | None) -> str | None:
    if not raw:
        return None
    value = raw.strip()
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc).isoformat()
    except ValueError:
        try:
            return parsedate_to_datetime(value).astimezone(timezone.utc).isoformat()
        except (TypeError, ValueError, OverflowError):
            return None


def date_from_listing_text(value: str) -> str | None:
    month_match = re.search(
        r"\b(Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|"
        r"Jul(?:y)?|Aug(?:ust)?|Sep(?:tember)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)"
        r"\s+\d{1,2},\s+\d{4}\b",
        value,
        flags=re.IGNORECASE,
    )
    numeric_match = re.search(r"\b\d{1,2}/\d{1,2}/\d{4}\b", value)
    for match, formats in (
        (month_match, ("%B %d, %Y", "%b %d, %Y")),
        (numeric_match, ("%m/%d/%Y",)),
    ):
        if not match:
            continue
        for date_format in formats:
            try:
                return datetime.strptime(match.group(0), date_format).replace(tzinfo=timezone.utc).isoformat()
            except ValueError:
                continue
    return None


def fetch_feed(url: str) -> list[dict]:
    response = requests.get(url, timeout=REQUEST_TIMEOUT, headers={"User-Agent": USER_AGENT})
    response.raise_for_status()
    parsed = feedparser.parse(response.content)
    if parsed.bozo and not parsed.entries:
        raise RuntimeError(f"invalid feed: {parsed.bozo_exception}")
    if not parsed.entries:
        raise RuntimeError("feed contained no articles")
    return [{
        "title": clean_html(e.get("title")),
        "url": e.get("link", "").strip(),
        "published_at": normalize_date(e),
        "excerpt": clean_html(e.get("summary") or e.get("description")),
        "title_checked": True,
    } for e in parsed.entries[:MAX_ITEMS_PER_SOURCE] if e.get("title") and e.get("link") and is_article_url(e.get("link", ""))]


def robots_allows(page_url: str) -> bool:
    parsed = urlparse(page_url)
    root = f"{parsed.scheme}://{parsed.netloc}"
    rp = robots_cache.get(root)
    try:
        if rp is None:
            rp = RobotFileParser(urljoin(root, "/robots.txt"))
            rp.read()
            robots_cache[root] = rp
        return rp.can_fetch(USER_AGENT, page_url)
    except Exception as exc:
        log.warning("robots.txt could not be read for %s: %s; skipping scrape", page_url, exc)
        return False


def discover_feed(site_url: str) -> str | None:
    response = requests.get(site_url, timeout=REQUEST_TIMEOUT, headers={"User-Agent": USER_AGENT})
    response.raise_for_status()
    soup = BeautifulSoup(response.text, "html.parser")
    link = soup.find("link", attrs={"type": lambda value: value and "rss" in value.lower()})
    return urljoin(site_url, link.get("href")) if link and link.get("href") else None


def scrape_listing(site_url: str, config: dict) -> list[dict]:
    if not robots_allows(site_url):
        raise RuntimeError("robots.txt does not allow listing-page scraping")
    response = requests.get(site_url, timeout=REQUEST_TIMEOUT, headers={"User-Agent": USER_AGENT})
    response.raise_for_status()
    soup = BeautifulSoup(response.text, "html.parser")
    results, seen = [], set()
    listing_selector = config.get("listing_selector")
    anchors = soup.select(listing_selector) if listing_selector else soup.select(
        "article h2 a[href], article h3 a[href], main h2 a[href], main h3 a[href]"
    )
    if config.get("include_paths") and not listing_selector:
        anchors.extend(soup.select("main a[href], article a[href]"))
    for anchor in anchors:
        selected_title = anchor.select_one(config.get("title_selector", "")) if config.get("title_selector") else None
        title_node = selected_title if selected_title is not None else anchor
        title = clean_html(title_node.get_text(" ", strip=True), 180)
        url = urljoin(site_url, anchor.get("href", ""))
        if len(title) < 12 or url in seen or not source_allows_url(url, config):
            continue
        container_class = config.get("listing_container_class")
        if config.get("listing_container_self") or (container_class and container_class in anchor.get("class", [])):
            node = anchor
        else:
            node = (
                anchor.find_parent(class_=container_class)
                if container_class
                else anchor.find_parent(["article", "li"])
            ) or anchor.parent
        date_node = node.select_one("time")
        raw_date = date_node.get("datetime") if date_node else None
        raw_date = normalize_raw_date(raw_date) or date_from_listing_text(node.get_text(" ", strip=True))
        excerpt_node = node.select_one(config.get("excerpt_selector", "p"))
        results.append({
            "title": title, "url": url, "published_at": raw_date,
            "excerpt": clean_html(excerpt_node.get_text(" ") if excerpt_node else ""),
            "title_checked": bool(config.get("listing_titles_canonical")),
        })
        seen.add(url)
        if len(results) >= MAX_ITEMS_PER_SOURCE:
            break
    if not results:
        raise RuntimeError("listing structure yielded no articles")
    return results


def find_structured_metadata(value) -> tuple[str | None, str | None]:
    if isinstance(value, dict):
        published = value.get("datePublished") or value.get("dateCreated") or value.get("uploadDate")
        description = value.get("description")
        if published:
            return str(published), str(description) if description else None
        for child in value.values():
            found_date, found_description = find_structured_metadata(child)
            if found_date:
                return found_date, found_description
    elif isinstance(value, list):
        for child in value:
            found_date, found_description = find_structured_metadata(child)
            if found_date:
                return found_date, found_description
    return None, None


def fetch_article_metadata(article_url: str) -> tuple[str | None, str | None, str | None]:
    if not robots_allows(article_url):
        return None, None, None
    response = requests.get(article_url, timeout=REQUEST_TIMEOUT, headers={"User-Agent": USER_AGENT})
    response.raise_for_status()
    soup = BeautifulSoup(response.text, "html.parser")

    date_selectors = (
        'meta[property="article:published_time"]', 'meta[name="article:published_time"]',
        'meta[name="pubdate"]', 'meta[name="publish-date"]', 'meta[itemprop="datePublished"]',
    )
    published = None
    for selector in date_selectors:
        node = soup.select_one(selector)
        if node and node.get("content"):
            published = normalize_raw_date(node.get("content"))
            if published:
                break
    if not published:
        time_node = soup.select_one('time[datetime]')
        published = normalize_raw_date(time_node.get("datetime")) if time_node else None

    description_node = soup.select_one('meta[name="description"], meta[property="og:description"]')
    description = description_node.get("content") if description_node else None
    heading_node = soup.select_one("main h1, article h1, h1")
    canonical_title = clean_html(heading_node.get_text(" ", strip=True), 300) if heading_node else None
    if not canonical_title:
        title_node = soup.select_one('meta[property="og:title"], meta[name="twitter:title"]')
        canonical_title = clean_html(title_node.get("content"), 300) if title_node and title_node.get("content") else None

    if not published:
        for script in soup.select('script[type="application/ld+json"]'):
            try:
                structured_date, structured_description = find_structured_metadata(json.loads(script.string or ""))
            except (json.JSONDecodeError, TypeError):
                continue
            published = normalize_raw_date(structured_date)
            description = description or structured_description
            if published:
                break
    return published, clean_html(description) if description else None, canonical_title


def enrich_articles(articles: list[dict]) -> list[dict]:
    with db() as conn:
        existing = {
            row["url"]: dict(row)
            for row in conn.execute("SELECT url,title,published_at,excerpt,title_checked_at FROM articles WHERE url IN (%s)" % ",".join(["?"] * len(articles)), [article["url"] for article in articles]).fetchall()
        } if articles else {}

    for article in articles:
        saved = existing.get(article["url"], {})
        article["published_at"] = normalize_raw_date(article.get("published_at")) or saved.get("published_at")
        article["excerpt"] = article.get("excerpt") or saved.get("excerpt") or ""
        article["title_checked"] = bool(article.get("title_checked") or saved.get("title_checked_at"))
        if article["published_at"] and article["title_checked"]:
            continue
        try:
            published, description, canonical_title = fetch_article_metadata(article["url"])
            article["published_at"] = article["published_at"] or published
            article["excerpt"] = article["excerpt"] or description or ""
            if canonical_title:
                article["title"] = canonical_title
                article["title_checked"] = True
        except Exception as exc:
            log.warning("article metadata unavailable | url=%s | %s", article["url"], exc)
        time.sleep(0.5)
    return articles


def repair_missing_dates(limit: int = 50) -> tuple[int, int]:
    with db() as conn:
        rows = conn.execute(
            "SELECT url,excerpt FROM articles WHERE published_at IS NULL AND metadata_checked_at IS NULL ORDER BY fetched_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
    repaired = 0
    for row in rows:
        published, description = None, None
        try:
            published, description, _ = fetch_article_metadata(row["url"])
        except Exception as exc:
            log.warning("date repair unavailable | url=%s | %s", row["url"], exc)
        checked_at = datetime.now().astimezone().isoformat()
        with db() as conn:
            conn.execute(
                """UPDATE articles SET published_at=COALESCE(published_at,?),
                   excerpt=CASE WHEN excerpt='' THEN ? ELSE excerpt END,
                   metadata_checked_at=? WHERE url=?""",
                (published, description or "", checked_at, row["url"]),
            )
        repaired += 1 if published else 0
        time.sleep(0.5)
    return repaired, len(rows)


def repair_unverified_titles(limit: int = 60) -> tuple[int, int]:
    with db() as conn:
        rows = conn.execute(
            "SELECT url,title FROM articles WHERE title_checked_at IS NULL ORDER BY fetched_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
    repaired = 0
    for row in rows:
        canonical_title = None
        try:
            _, _, canonical_title = fetch_article_metadata(row["url"])
        except Exception as exc:
            log.warning("title repair unavailable | url=%s | %s", row["url"], exc)
        checked_at = datetime.now().astimezone().isoformat()
        with db() as conn:
            conn.execute(
                "UPDATE articles SET title=CASE WHEN ?<>'' THEN ? ELSE title END,title_checked_at=? WHERE url=?",
                (canonical_title or "", canonical_title or "", checked_at, row["url"]),
            )
        repaired += 1 if canonical_title and canonical_title != row["title"] else 0
        time.sleep(0.5)
    return repaired, len(rows)


def collect_source(source_id: str, config: dict) -> tuple[list[dict], str]:
    errors = []
    feed_candidates = list(config["feeds"])
    collected_articles = None
    method = None
    for feed_url in feed_candidates:
        try:
            articles = filter_source_articles(fetch_feed(feed_url), config)
            if not articles:
                raise RuntimeError("feed contained no matching articles")
            collected_articles = articles
            method = f"RSS {feed_url}"
            break
        except Exception as exc:
            errors.append(f"{feed_url}: {exc}")
    if collected_articles is None:
        try:
            discovered = discover_feed(config["site"])
            if discovered and discovered not in feed_candidates:
                articles = filter_source_articles(fetch_feed(discovered), config)
                if not articles:
                    raise RuntimeError("discovered feed contained no matching articles")
                collected_articles = articles
                method = f"discovered RSS {discovered}"
        except Exception as exc:
            errors.append(f"feed discovery: {exc}")
    if collected_articles is None:
        try:
            collected_articles = scrape_listing(config["site"], config)
            method = "HTML fallback"
        except Exception as exc:
            errors.append(f"fallback: {exc}")
    if collected_articles is None:
        raise RuntimeError("; ".join(errors))

    combined = {article["url"]: article for article in collected_articles}
    for archive_url in config.get("archive_pages", []):
        archive_config = {
            **config,
            "listing_selector": config.get("archive_listing_selector"),
            "listing_container_class": config.get("archive_container_class"),
            "listing_titles_canonical": config.get("archive_titles_canonical", False),
            "title_selector": config.get("archive_title_selector"),
            "excerpt_selector": config.get("archive_excerpt_selector", "p"),
        }
        try:
            archive_articles = scrape_listing(archive_url, archive_config)
            for article in archive_articles:
                combined.setdefault(article["url"], article)
            method += f" + archive {archive_url}"
        except Exception as exc:
            log.warning("archive unavailable | source=%s | url=%s | %s", source_id, archive_url, exc)

    return list(combined.values()), method


def save_articles(source_id: str, articles: list[dict]) -> int:
    now = datetime.now().astimezone().isoformat()
    with db() as conn:
        existing_urls = {
            row["url"]
            for row in conn.execute("SELECT url FROM articles WHERE url IN (%s)" % ",".join(["?"] * len(articles)), [article["url"] for article in articles]).fetchall()
        } if articles else set()
        new_count = 0
        for article in articles:
            is_new_url = article["url"] not in existing_urls
            title_checked_at = now if article.get("title_checked") else None
            conn.execute(
                """INSERT INTO articles(source_id,title,url,published_at,excerpt,fetched_at,title_checked_at) VALUES(?,?,?,?,?,?,?)
                   ON CONFLICT(url) DO UPDATE SET
                     source_id=excluded.source_id,
                     title=CASE WHEN excluded.title_checked_at IS NOT NULL THEN excluded.title ELSE articles.title END,
                     title_checked_at=COALESCE(articles.title_checked_at,excluded.title_checked_at),
                     published_at=COALESCE(excluded.published_at,articles.published_at),
                     excerpt=CASE WHEN articles.excerpt='' THEN excluded.excerpt ELSE articles.excerpt END""",
                (source_id, article["title"], article["url"], article.get("published_at"), article.get("excerpt", ""), now, title_checked_at),
            )
            if is_new_url:
                new_count += 1
                existing_urls.add(article["url"])
    return new_count


def refresh_all(trigger: str = "manual") -> dict:
    if not refresh_lock.acquire(blocking=False):
        return {"status": "busy", "message": "A refresh is already running."}
    started = datetime.now().astimezone().isoformat()
    with db() as conn:
        run_id = conn.execute("INSERT INTO runs(started_at,trigger,status) VALUES(?,?,?)", (started, trigger, "running")).lastrowid
    summary, failures = {}, 0
    log.info("refresh started | trigger=%s", trigger)
    try:
        for index, (source_id, config) in enumerate(SOURCES.items()):
            error = None
            for attempt in (1, 2):
                try:
                    articles, method = collect_source(source_id, config)
                    articles = enrich_articles(articles)
                    count = save_articles(source_id, articles)
                    summary[source_id] = {"new": count, "fetched": len(articles), "method": method}
                    log.info("source=%s | new=%d | fetched=%d | method=%s | attempt=%d", source_id, count, len(articles), method, attempt)
                    error = None
                    break
                except Exception as exc:
                    error = str(exc)
                    log.warning("source=%s | attempt=%d failed | %s", source_id, attempt, error)
                    if attempt == 1:
                        time.sleep(2)
            if error:
                failures += 1
                summary[source_id] = {"new": 0, "error": error}
                log.error("source=%s | failed after retry | %s", source_id, error)
            if index < len(SOURCES) - 1:
                time.sleep(0.75)
        repaired_dates, checked_dates = repair_missing_dates()
        if checked_dates:
            log.info("date repair finished | repaired=%d | checked=%d", repaired_dates, checked_dates)
        repaired_titles, checked_titles = repair_unverified_titles()
        if checked_titles:
            log.info("title repair finished | changed=%d | checked=%d", repaired_titles, checked_titles)
        finished = datetime.now().astimezone().isoformat()
        status = "success" if failures == 0 else ("partial" if failures < len(SOURCES) else "failed")
        with db() as conn:
            conn.execute("UPDATE runs SET finished_at=?,status=?,details=? WHERE id=?", (finished, status, json.dumps(summary), run_id))
            conn.execute("INSERT OR REPLACE INTO metadata(key,value) VALUES('last_updated',?)", (finished,))
        log.info("refresh finished | status=%s | failures=%d", status, failures)
        return {"status": status, "last_updated": finished, "sources": summary}
    finally:
        refresh_lock.release()


@app.get("/")
def index():
    return render_template("index.html")


@app.get("/api/articles")
def articles_api():
    return jsonify(dashboard_payload(request.args.get("limit", type=int)))


def dashboard_payload(limit: int | None = None) -> dict:
    """Return the serializable dashboard data used by Flask and GitHub Pages."""
    if limit is not None:
        limit = min(max(limit, 1), 1000)
    grouped = {}
    with db() as conn:
        last = conn.execute("SELECT value FROM metadata WHERE key='last_updated'").fetchone()
        latest_run = conn.execute("SELECT status FROM runs ORDER BY id DESC LIMIT 1").fetchone()
        for source_id, config in SOURCES.items():
            query = (
                "SELECT title,url,published_at,excerpt,fetched_at FROM articles "
                "WHERE source_id=? ORDER BY COALESCE(published_at,fetched_at) DESC"
            )
            rows = conn.execute(
                query + (" LIMIT ?" if limit is not None else ""),
                (source_id, limit) if limit is not None else (source_id,),
            ).fetchall()
            grouped[source_id] = {**config, "articles": [dict(row) for row in rows]}
    return {
        "last_updated": last["value"] if last else None,
        "run_status": latest_run["status"] if latest_run else None,
        "sources": grouped,
    }


@app.post("/api/refresh")
def refresh_api():
    if refresh_lock.locked():
        return jsonify({"status": "busy", "message": "A refresh is already running."}), 409
    threading.Thread(target=refresh_all, args=("manual",), daemon=True).start()
    return jsonify({"status": "started"}), 202


def scheduled_refresh() -> None:
    refresh_all("scheduled")


init_db()


def start_background_services() -> None:
    """Start services needed only by the local Flask edition."""
    scheduler.add_job(
        scheduled_refresh,
        "cron",
        day_of_week="mon,thu",
        hour=10,
        minute=0,
        id="twice_weekly_refresh",
        max_instances=1,
        coalesce=True,
    )
    scheduler.start()
    atexit.register(lambda: scheduler.shutdown(wait=False) if scheduler.running else None)
    with db() as conn:
        first_run = conn.execute("SELECT 1 FROM articles LIMIT 1").fetchone() is None
    if first_run:
        threading.Thread(target=refresh_all, args=("startup",), daemon=True).start()

if __name__ == "__main__":
    start_background_services()
    log.info("server starting | scheduler=Monday,Thursday 10:00 | timezone=%s", datetime.now().astimezone().tzinfo)
    app.run(host="127.0.0.1", port=int(os.environ.get("PORT", "5050")), debug=False)
