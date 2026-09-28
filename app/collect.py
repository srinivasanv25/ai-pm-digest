"""Deterministic collection: RSS/Atom feeds in, candidate items out.

No LLM here. Everything the editor can pick from is produced by this module
(feed items) or by the scout's grounding metadata (search sources).
"""

import asyncio
import calendar
import html
import json
import logging
import re
import time
from datetime import UTC, date, datetime, timedelta
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import feedparser
import fsspec
import httpx
import yaml

from app import config

log = logging.getLogger(__name__)

_TRACKING_PARAMS = re.compile(r"^(utm_|ref$|ref_src$|source$|fbclid$|gclid$|mc_)")
_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")


def normalize_url(url: str) -> str:
    """Canonical form for dedup: https, no fragment, no tracking params, no trailing slash."""
    parts = urlsplit(url.strip())
    query = urlencode(
        [(k, v) for k, v in parse_qsl(parts.query) if not _TRACKING_PARAMS.match(k)]
    )
    path = parts.path.rstrip("/") or "/"
    return urlunsplit(
        ("https", parts.netloc.lower().removeprefix("www."), path, query, "")
    )


def clean_text(raw: str, limit: int = config.SUMMARY_CHARS) -> str:
    text = _WS_RE.sub(" ", html.unescape(_TAG_RE.sub(" ", raw or ""))).strip()
    return text if len(text) <= limit else text[: limit - 1].rsplit(" ", 1)[0] + "…"


# --- Sent-history store (memory across days) --------------------------------
# Local files by default; any fsspec URI (gs://bucket/prefix) when deployed.


def local_today() -> date:
    return datetime.now(config.TIMEZONE).date()


def _state_path(name: str) -> str:
    return f"{config.STATE_URI.rstrip('/')}/{name}"


def _read_state(name: str, default):
    try:
        with fsspec.open(_state_path(name), "r") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def _write_state(name: str, data) -> None:
    with fsspec.open(_state_path(name), "w", auto_mkdir=True) as f:
        json.dump(data, f, indent=1, sort_keys=isinstance(data, dict))


def load_seen() -> dict[str, str]:
    """Map of normalized URL -> ISO date it was sent, pruned to the retention window."""
    cutoff = local_today() - timedelta(days=config.SEEN_RETENTION_DAYS)
    seen = _read_state(config.SEEN_NAME, {})
    return {u: d for u, d in seen.items() if date.fromisoformat(d) >= cutoff}


def record_seen(urls: list[str]) -> None:
    seen = load_seen()
    today = local_today().isoformat()
    seen.update({normalize_url(u): today for u in urls})
    _write_state(config.SEEN_NAME, seen)


def _load_sent_log() -> list[dict]:
    cutoff = local_today() - timedelta(days=config.SEEN_RETENTION_DAYS)
    return [
        e
        for e in _read_state(config.SENT_LOG_NAME, [])
        if date.fromisoformat(e["date"]) >= cutoff
    ]


def load_recent_headlines() -> list[str]:
    """Headlines sent in the last few days, so the same story from a new URL is skipped."""
    cutoff = local_today() - timedelta(days=config.RECENT_HEADLINE_DAYS)
    return [
        e["headline"]
        for e in _load_sent_log()
        if date.fromisoformat(e["date"]) >= cutoff
    ]


def sent_today() -> bool:
    """Once-a-day guard, so a retried or duplicate trigger never sends twice."""
    today = local_today().isoformat()
    return any(e["date"] == today for e in _load_sent_log())


def record_sent_headlines(headlines: list[str]) -> None:
    today = local_today().isoformat()
    _write_state(
        config.SENT_LOG_NAME,
        _load_sent_log() + [{"date": today, "headline": h} for h in headlines],
    )


_NON_ARTICLE_RE = re.compile(
    r"/(category|categories|tag|tags|topic|topics|section|author|authors|search)(/|$)"
)


def is_article_url(url: str) -> bool:
    """Reject homepages and index pages (category/tag/topic listings)."""
    path = urlsplit(url).path.rstrip("/")
    if not path or _NON_ARTICLE_RE.search(path + "/"):
        return False
    return True


# --- Feed collection --------------------------------------------------------


def load_feed_config() -> list[dict]:
    return yaml.safe_load(config.FEEDS_FILE.read_text())["feeds"]


async def _fetch_one(client: httpx.AsyncClient, feed: dict, now: float) -> list[dict]:
    resp = await client.get(feed["url"])
    resp.raise_for_status()
    parsed = feedparser.parse(resp.content)
    max_age = feed.get("max_age_hours", 36) * 3600
    items = []
    for entry in parsed.entries:
        stamp = entry.get("published_parsed") or entry.get("updated_parsed")
        if not stamp or now - calendar.timegm(stamp) > max_age:
            continue
        link = entry.get("link")
        title = clean_text(entry.get("title", ""), 200)
        if not link or not title:
            continue
        items.append(
            {
                "title": title,
                "url": link,
                "source": feed["name"],
                "published": datetime.fromtimestamp(
                    calendar.timegm(stamp), UTC
                ).strftime("%Y-%m-%d %H:%M UTC"),
                "summary": clean_text(entry.get("summary", "")),
            }
        )
        if len(items) >= feed.get("max_items", 10):
            break
    return items


async def collect_feeds(
    seen: dict[str, str] | None = None,
) -> tuple[list[dict], list[str]]:
    """Fetch every feed concurrently.

    Returns (candidates, failed_feed_names). Each candidate gets a stable short
    id (f1, f2, …) that the editor must cite instead of a URL.
    """
    seen = seen if seen is not None else load_seen()
    feeds = load_feed_config()
    now = time.time()
    async with httpx.AsyncClient(
        timeout=config.FEED_TIMEOUT_SECONDS,
        follow_redirects=True,
        headers={"User-Agent": config.USER_AGENT},
    ) as client:
        results = await asyncio.gather(
            *(_fetch_one(client, f, now) for f in feeds), return_exceptions=True
        )

    failed, candidates, urls_in_run = [], [], set()
    for feed, result in zip(feeds, results, strict=True):
        if isinstance(result, BaseException):
            log.warning("feed failed: %s (%s)", feed["name"], result)
            failed.append(feed["name"])
            continue
        for item in result:
            key = normalize_url(item["url"])
            if key in seen or key in urls_in_run:
                continue
            urls_in_run.add(key)
            candidates.append(item)

    candidates = candidates[: config.MAX_CANDIDATES]
    for i, item in enumerate(candidates, start=1):
        item["id"] = f"f{i}"
    return candidates, failed
