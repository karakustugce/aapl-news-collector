"""Fetch each source and map it into the raw-event contract.

Each fetcher returns (rows, error). A failing source never stops the run;
its error is written to the run report instead.
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from urllib.parse import quote, urlparse

import feedparser
import requests

UA_DEFAULT = "aapl-news-collector research (set SEC_USER_AGENT to 'Name email')"
BACKFILL_HOURS = 6

GDELT_QUERY = '("Apple Inc" OR AAPL OR "Tim Cook" OR iPhone OR "App Store" OR "Apple Intelligence") sourcelang:english'
GOOGLE_QUERY = 'Apple (AAPL OR iPhone OR "Tim Cook") when:2d'


def iso(v) -> str | None:
    """Parse GDELT '20261024T123000Z', RFC 822 dates, or ISO strings to UTC ISO."""
    if v is None or v == "":
        return None
    if isinstance(v, datetime):
        d = v
    else:
        s = str(v)
        m = re.fullmatch(r"(\d{4})(\d{2})(\d{2})T(\d{2})(\d{2})(\d{2})Z", s)
        try:
            if m:
                d = datetime(*map(int, m.groups()), tzinfo=timezone.utc)
            elif re.match(r"^\d{4}-\d{2}-\d{2}", s):
                d = datetime.fromisoformat(s.replace("Z", "+00:00"))
            else:
                d = parsedate_to_datetime(s)
        except (ValueError, TypeError):
            return None
    if d.tzinfo is None:
        d = d.replace(tzinfo=timezone.utc)
    return d.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def availability(published: str | None, first_seen: str) -> tuple[str, str]:
    """Live capture -> first_seen. Old item (backfill) -> published + 15 min, labeled."""
    if not published:
        return first_seen, "observed_no_pubdate"
    lag_h = (datetime.fromisoformat(first_seen.replace("Z", "+00:00"))
             - datetime.fromisoformat(published.replace("Z", "+00:00"))).total_seconds() / 3600
    if lag_h <= BACKFILL_HOURS:
        return first_seen, "observed"
    a = datetime.fromisoformat(published.replace("Z", "+00:00")) + timedelta(minutes=15)
    return a.isoformat().replace("+00:00", "Z"), "backfill_published_plus_15m"


def domain_of(u: str | None) -> str | None:
    try:
        return urlparse(u).hostname.removeprefix("www.").lower()
    except (AttributeError, ValueError):
        return None


def make_row(run: dict, source: str, *, source_record_id=None, published=None, url=None, title="",
             text_raw="", source_domain=None, language=None, raw=None) -> dict:
    pub = iso(published)
    avail, basis = availability(pub, run["first_seen_at_utc"])
    return {
        "source": source,
        "source_record_id": str(source_record_id) if source_record_id else None,
        "published_at_utc": pub,
        "first_seen_at_utc": run["first_seen_at_utc"],
        "available_at_utc": avail,
        "availability_basis": basis,
        "ingestion_run_id": run["run_id"],
        "query_version": run["query_version"],
        "url": url,
        "title": (title or "").strip(),
        "text_raw": (text_raw or "")[:5000],
        "source_domain": source_domain or domain_of(url),
        "language": language,
        "raw_payload": raw or {},
    }


# ------------------------------------------------------------------ GDELT
def parse_gdelt(payload: dict, run: dict) -> list[dict]:
    return [make_row(run, "gdelt", source_record_id=a.get("url"), published=a.get("seendate"), url=a.get("url"),
                     title=a.get("title"), source_domain=a.get("domain"), language=a.get("language"),
                     raw={k: a.get(k) for k in ("seendate", "domain", "sourcecountry", "language")})
            for a in payload.get("articles", [])]


def fetch_gdelt(run: dict, session: requests.Session):
    url = ("https://api.gdeltproject.org/api/v2/doc/doc?query=" + quote(GDELT_QUERY)
           + "&mode=artlist&format=json&timespan=2d&maxrecords=250&sort=datedesc")
    r = session.get(url, timeout=30)
    r.raise_for_status()
    if not r.text.strip().startswith("{"):   # GDELT returns plain-text errors / rate limits
        raise RuntimeError(f"GDELT non-JSON response: {r.text[:120]}")
    return parse_gdelt(r.json(), run)


# ------------------------------------------------------------------ RSS
def parse_google_news(feed, run: dict) -> list[dict]:
    rows = []
    for e in feed.entries:
        title = e.get("title", "")
        m = re.search(r"\s-\s([^-]{2,60})$", title)
        src = e.get("source") or {}
        publisher = src.get("title") or (m.group(1).strip() if m else None)
        dom = domain_of(src.get("href")) or (publisher or "news.google.com").lower()
        rows.append(make_row(run, "google_news", source_record_id=e.get("id") or e.get("link"),
                             published=e.get("published"), url=e.get("link"), title=title,
                             source_domain=dom, language="en",
                             raw={"publisher": publisher, "published": e.get("published")}))
    return rows


def parse_apple_newsroom(feed, run: dict) -> list[dict]:
    return [make_row(run, "apple_newsroom", source_record_id=e.get("id") or e.get("link"),
                     published=e.get("updated") or e.get("published"), url=e.get("link"), title=e.get("title"),
                     text_raw=re.sub(r"<[^>]+>", " ", e.get("summary", "")), source_domain="apple.com",
                     language="en", raw={"id": e.get("id")})
            for e in feed.entries]


def _feed(url: str, session: requests.Session):
    r = session.get(url, timeout=30)
    r.raise_for_status()
    return feedparser.parse(r.content)


def fetch_google_news(run, session):
    url = "https://news.google.com/rss/search?q=" + quote(GOOGLE_QUERY) + "&hl=en-US&gl=US&ceid=US:en"
    return parse_google_news(_feed(url, session), run)


def fetch_apple_newsroom(run, session):
    return parse_apple_newsroom(_feed("https://www.apple.com/newsroom/rss-feed.rss", session), run)


# ------------------------------------------------------------------ SEC
def parse_sec(payload: dict, run: dict, lookback_days: int = 30) -> list[dict]:
    r = payload.get("filings", {}).get("recent", {})
    since = datetime.now(timezone.utc) - timedelta(days=lookback_days)
    rows = []
    for k, acc in enumerate(r.get("accessionNumber", [])):
        accepted = iso(r["acceptanceDateTime"][k])
        if not accepted or datetime.fromisoformat(accepted.replace("Z", "+00:00")) < since:
            continue
        doc = r["primaryDocument"][k]
        form = r["form"][k]
        desc = (r.get("primaryDocDescription") or [""] * (k + 1))[k] or form
        rows.append(make_row(run, "sec_edgar", source_record_id=acc, published=accepted,
                             url=f"https://www.sec.gov/Archives/edgar/data/320193/{acc.replace('-', '')}/{doc}",
                             title=f"Apple {form}: {desc}", source_domain="sec.gov", language="en",
                             raw={"form": form, "filingDate": r["filingDate"][k],
                                  "items": (r.get("items") or [None] * (k + 1))[k]}))
    return rows


def fetch_sec(run, session, user_agent: str):
    r = session.get("https://data.sec.gov/submissions/CIK0000320193.json", timeout=30,
                    headers={"User-Agent": user_agent, "Accept": "application/json"})
    r.raise_for_status()
    return parse_sec(r.json(), run)


def fetch_all(run: dict, sec_user_agent: str | None = None) -> tuple[list[dict], dict]:
    s = requests.Session()
    s.headers["User-Agent"] = UA_DEFAULT
    fetchers = {
        "gdelt": lambda: fetch_gdelt(run, s),
        "google_news": lambda: fetch_google_news(run, s),
        "apple_newsroom": lambda: fetch_apple_newsroom(run, s),
        "sec_edgar": lambda: fetch_sec(run, s, sec_user_agent or UA_DEFAULT),
    }
    rows, report = [], {}
    for name, fn in fetchers.items():
        last_err = None
        for attempt in range(3):
            try:
                got = fn()
                rows += got
                report[name] = {"returned": len(got), "failed": None}
                break
            except Exception as e:  # noqa: BLE001 - one source must not kill the run
                last_err = f"{type(e).__name__}: {e}"[:300]
        else:
            report[name] = {"returned": 0, "failed": last_err}
    return rows, report
