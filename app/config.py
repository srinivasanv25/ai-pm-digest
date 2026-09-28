"""Paths and tunables for the digest. Secrets come from the environment, never from here."""

import os
from pathlib import Path
from zoneinfo import ZoneInfo

PROJECT_ROOT = Path(__file__).resolve().parent.parent
FEEDS_FILE = Path(__file__).resolve().parent / "feeds.yaml"
DATA_DIR = PROJECT_ROOT / "data"

# Where sent-history lives: local data/ by default, or e.g. gs://my-bucket/digest
# when deployed (Cloud Run containers start fresh on every run).
STATE_URI = os.getenv("DIGEST_STATE_URI") or str(DATA_DIR)
SEEN_NAME = "seen_urls.json"
SENT_LOG_NAME = "sent_headlines.json"

# "Today" for the digest (dedup dates, once-a-day guard) is the reader's local day.
TIMEZONE = ZoneInfo(os.getenv("DIGEST_TIMEZONE", "America/Los_Angeles"))
OUT_DIR = PROJECT_ROOT / "out"
FIXTURES_DIR = PROJECT_ROOT / "tests" / "eval" / "fixtures"

# Digest shape
MIN_ITEMS_TO_SEND = 3
MAX_ITEMS = 12
MAX_SCOUT_SOURCES = 8
SEEN_RETENTION_DAYS = 14
RECENT_HEADLINE_DAYS = 7  # stories sent this recently are skipped even via a new URL

# Feed collection
FEED_TIMEOUT_SECONDS = 20
SUMMARY_CHARS = 350
MAX_CANDIDATES = 140
USER_AGENT = "ai-pm-digest/0.1 (personal RSS reader)"

SECTIONS = {
    "models": "Models & lab releases",
    "builder": "Builder tools & launches",
    "strategy": "Product & strategy",
    "research": "Research worth knowing",
}
