"""Supabase writes through service-role-only RPC functions (see supabase/migrations)."""
from __future__ import annotations

import os

import requests


class Store:
    def __init__(self, url: str | None = None, key: str | None = None):
        self.url = (url or os.environ["SUPABASE_URL"]).rstrip("/")
        key = key or os.environ["SUPABASE_SERVICE_KEY"]
        self.h = {"apikey": key, "Content-Type": "application/json"}
        if key.startswith("eyJ"):                 # legacy JWT keys also go in Authorization
            self.h["Authorization"] = f"Bearer {key}"

    def rpc(self, fn: str, payload: dict):
        r = requests.post(f"{self.url}/rest/v1/rpc/{fn}", json=payload, headers=self.h, timeout=60)
        if r.status_code >= 300:
            raise RuntimeError(f"{fn} -> {r.status_code}: {r.text[:300]}")
        return r.json() if r.text else None

    def start_run(self, run: dict):
        self.rpc("aapl_start_run", {"run": run})

    def ingest(self, rows: list[dict]) -> tuple[int, int]:
        new = dup = 0
        for i in range(0, len(rows), 500):
            res = self.rpc("aapl_ingest_events", {"rows": rows[i : i + 500]})
            new += res[0]["inserted"]
            dup += res[0]["duplicates"]
        return new, dup

    def unlabeled(self, n: int = 40) -> list[dict]:
        return self.rpc("aapl_unlabeled", {"max_rows": n}) or []

    def set_labels(self, labels: list[dict]) -> int:
        return self.rpc("aapl_set_labels", {"rows": labels}) if labels else 0

    def finish_run(self, run: dict):
        self.rpc("aapl_finish_run", {"run": run})
