import json
from pathlib import Path

import feedparser

from collector.audit import audit, canonical_url
from collector.labeler import validate
from collector.sources import parse_apple_newsroom, parse_gdelt, parse_google_news, parse_sec, iso

F = Path(__file__).parent / "fixtures"
RUN = {"run_id": "test", "query_version": "t", "first_seen_at_utc": iso(__import__("datetime").datetime.now(__import__("datetime").timezone.utc))}


def rows():
    r = parse_gdelt(json.loads((F / "gdelt.json").read_text()), RUN)
    r += parse_google_news(feedparser.parse((F / "google_news.xml").read_bytes()), RUN)
    r += parse_apple_newsroom(feedparser.parse((F / "apple_newsroom.xml").read_bytes()), RUN)
    r += parse_sec(json.loads((F / "sec.json").read_text()), RUN)
    return audit(r)


def test_every_row_meets_contract():
    req = ["idempotency_key", "source", "first_seen_at_utc", "available_at_utc", "availability_basis",
           "ingestion_run_id", "query_version", "title", "content_hash", "relevance_rule"]
    out = rows()
    assert len(out) == 8   # 4 GDELT + 2 Google + 1 Newsroom + 1 recent SEC filing
    for r in out:
        assert all(r.get(k) for k in req), r
        assert r["available_at_utc"] <= r["first_seen_at_utc"] or r["availability_basis"] == "observed"


def test_relevance_and_fruit_filter():
    rel = {r["title"]: r["relevance_rule"] for r in rows()}
    assert rel["Best apple pie recipe for fall"] == "reject"
    assert rel["Apple shares slip as markets wobble"] == "weak"
    assert rel["Apple reports fourth quarter results"] == "primary"
    assert rel["Apple iPhone 17 demand beats estimates"] == "strong"


def test_backfill_is_labeled_and_old_filings_dropped():
    out = rows()
    old = [r for r in out if r["source_domain"] == "cnbc.com"][0]
    assert old["availability_basis"] == "backfill_published_plus_15m"
    sec = [r for r in out if r["source"] == "sec_edgar"]
    assert len(sec) == 1 and sec[0]["title"].startswith("Apple 8-K")


def test_same_story_across_outlets_shares_cluster():
    out = rows()
    h = {r["source_domain"]: r["content_hash"] for r in out if "demand beats" in r["title"]}
    assert len(set(h.values())) == 1 and len(h) == 3


def test_canonical_url_strips_tracking():
    assert canonical_url("https://www.Reuters.com/a/?utm_source=x&id=3#top") == "reuters.com/a?id=3"


def test_label_validator_rejects_invented_fields():
    sent = [{"idempotency_key": "k1", "title": "EU fines Apple over App Store rules", "text_raw": ""}]
    raw = [{"idempotency_key": "k1", "is_apple_company": True, "event_type": "lawsuit", "sentiment": -3,
            "sentiment_basis": "invented quote", "novelty": "new_information", "confidence": 0.9},
           {"idempotency_key": "not-sent", "is_apple_company": True, "event_type": "product", "sentiment": 1}]
    out = validate(raw, sent)
    assert len(out) == 1
    assert out[0]["event_type"] == "other" and out[0]["sentiment"] == -1.0 and out[0]["sentiment_basis"] == ""
