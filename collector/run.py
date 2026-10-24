"""One collection run: fetch -> audit -> store -> label -> report.

    python -m collector.run            # writes to Supabase (needs env vars)
    python -m collector.run --dry-run  # prints what it would store
"""
from __future__ import annotations

import argparse
import json
import os
from collections import Counter
from datetime import datetime, timezone

from .audit import audit
from .labeler import label
from .sources import fetch_all

QUERY_VERSION = "aapl-v2-2026-10-24"


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--label-max", type=int, default=int(os.environ.get("LABEL_MAX", "40")))
    a = ap.parse_args(argv)

    started = now_iso()
    run = {"run_id": f"gha-{os.environ.get('GITHUB_RUN_ID', 'local')}-{started.replace(':', '').replace('-', '')}",
           "query_version": QUERY_VERSION, "started_at_utc": started, "first_seen_at_utc": started}

    raw, report = fetch_all(run, os.environ.get("SEC_USER_AGENT"))
    rows = audit(raw)
    for src in report:
        c = Counter(r["relevance_rule"] for r in rows if r["source"] == src)
        report[src].update({k: c.get(k, 0) for k in ("primary", "strong", "weak", "reject")})

    if a.dry_run:
        print(json.dumps(report, indent=1))
        for r in rows[:15]:
            print(f"{r['source']:14s} {r['relevance_rule']:7s} {r['availability_basis']:28s} {r['title'][:70]}")
        return

    from .store import Store
    store = Store()
    store.start_run({k: run[k] for k in ("run_id", "query_version", "started_at_utc")})
    status, err, new, dup, n_lab = "ok", None, 0, 0, 0
    try:
        new, dup = store.ingest(rows)
        todo = store.unlabeled(a.label_max)
        n_lab = store.set_labels(label(todo))
    except Exception as e:  # noqa: BLE001
        status, err = "error", f"{type(e).__name__}: {e}"[:500]
    if any(v.get("failed") for v in report.values()) and status == "ok":
        status = "partial"
    store.finish_run({"run_id": run["run_id"], "finished_at_utc": now_iso(), "status": status, "sources": report,
                      "n_returned": len(rows), "n_new": new, "n_duplicate": dup, "n_labeled": n_lab, "error": err})
    print(f"{status}: returned={len(rows)} new={new} duplicate={dup} labeled={n_lab}")
    print(json.dumps(report))
    if status == "error":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
