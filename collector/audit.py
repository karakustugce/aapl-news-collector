"""Deterministic gate: canonical URL, keys, relevance rule, story clusters, issues.

Nothing is deleted here. Rows are flagged; storage keeps everything.
"""
from __future__ import annotations

import hashlib
import re
from urllib.parse import parse_qsl, urlencode, urlparse

STRONG = re.compile(r"\b(AAPL|Apple Inc|Tim Cook|Cupertino|iPhone|iPad|MacBook|Vision Pro|App Store|AirPods|"
                    r"Apple Watch|Apple Intelligence|iOS \d+|Apple Pay|Apple TV\+|Apple Music|Siri)\b", re.I)
APPLE = re.compile(r"\bApple('s)?\b")
FRUIT = re.compile(r"\b(apple (pie|cider|juice|orchard|tree|picking|recipe|crumble|sauce|vinegar)|big apple|orchard|harvest)\b", re.I)
TRACKING = re.compile(r"^(utm_|fbclid|gclid|mc_|cmpid|ref$)", re.I)


def h(s: str, n: int = 16) -> str:
    return hashlib.sha1(s.encode()).hexdigest()[:n]


def canonical_url(u: str | None) -> str | None:
    if not u:
        return None
    try:
        p = urlparse(u)
        q = urlencode([(k, v) for k, v in parse_qsl(p.query) if not TRACKING.match(k)])
        return (p.hostname or "").removeprefix("www.").lower() + p.path.rstrip("/") + (f"?{q}" if q else "")
    except ValueError:
        return None


def title_key(t: str) -> str:
    t = re.sub(r"\s[-|–]\s[^-|–]{2,60}$", "", t or "").lower()
    return " ".join(sorted({w for w in re.sub(r"[^a-z0-9 ]", " ", t).split() if len(w) > 2}))


def relevance(row: dict) -> str:
    if row["source"] in ("sec_edgar", "apple_newsroom"):
        return "primary"
    text = f"{row['title']} {row.get('text_raw', '')}"
    if STRONG.search(text):
        return "strong"
    if APPLE.search(text) and not FRUIT.search(text):
        return "weak"
    return "reject"


def audit(rows: list[dict]) -> list[dict]:
    out, seen = [], set()
    for r in rows:
        r = dict(r)
        r["canonical_url"] = canonical_url(r.get("url"))
        key_src = r.get("source_record_id") or r["canonical_url"] or r["title"]
        r["idempotency_key"] = f"{r['source']}:{h(str(key_src))}"
        if r["idempotency_key"] in seen:          # same item twice in one response
            continue
        seen.add(r["idempotency_key"])
        r["content_hash"] = h(title_key(r["title"]), 12)
        r["relevance_rule"] = relevance(r)
        issues = []
        if not r.get("published_at_utc"):
            issues.append("missing_published_at")
        elif r["published_at_utc"] > r["first_seen_at_utc"]:
            issues.append("published_in_future")
        if not r.get("url"):
            issues.append("missing_url")
        if not r["title"]:
            issues.append("missing_title")
        r["audit_issues"] = ",".join(issues)
        r["needs_agent_review"] = r["relevance_rule"] == "weak" or bool(issues)
        out.append(r)
    return out
