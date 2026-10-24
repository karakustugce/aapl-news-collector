# aapl-news-collector

Collects Apple-related news every 30 minutes, stores it in Supabase with a timestamp that says when each item became usable for forecasting, and labels it with a review agent. This is the data source for [Grid_Feature_Engineering](https://github.com/karakustugce/Grid_Feature_Engineering).

Dashboard: https://aapl-news-desk.vercel.app

```
GitHub Actions (every 30 min, weekends included)
  └─ collector/run.py
       ├─ sources.py   GDELT · Google News · Apple Newsroom · SEC EDGAR  → raw-event contract
       ├─ audit.py     canonical URL · idempotency key · story cluster · relevance (primary/strong/weak/reject)
       ├─ store.py     Supabase RPC (service role only) — first observation wins, never overwritten
       └─ labeler.py   Claude labels: event type, tone, novelty (only if ANTHROPIC_API_KEY is set)
Supabase schema aapl  →  public read-only views  →  dashboard/index.html on Vercel
```

## Setup (one time)

In the repo: **Settings → Secrets and variables → Actions → New repository secret**:

| Secret | Value |
|---|---|
| `SUPABASE_URL` | `https://zrqquefqdzdqnflirowm.supabase.co` |
| `SUPABASE_SERVICE_KEY` | Supabase → Project Settings → API Keys → **secret** key (`sb_secret_…`) or legacy `service_role` |
| `SEC_USER_AGENT` | `Your Name your@email.com` (SEC requires a contact) |
| `ANTHROPIC_API_KEY` | Optional. Without it the agent step is skipped and rows stay unlabeled |

Then **Actions → collect-news → Run workflow** for the first run. After that it runs on schedule.

## Timing rule

- `first_seen_at_utc`: when this collector first saw the item.
- `available_at_utc`: what the forecasting model may use. Seen within 6 h of publication → first seen (`observed`). Older → publication + 15 min, labeled `backfill_published_plus_15m`.
- Re-seeing an item never changes its stored row, so the first observation is the record.

## Local

```bash
pip install -r requirements.txt
pytest -q
python -m collector.run --dry-run      # fetch + audit, prints, writes nothing
```

## Export for the model

```sql
select idempotency_key, source, source_domain, title, text_raw, published_at_utc, available_at_utc,
       availability_basis, content_hash as cluster, relevance_rule, sentiment, event_type
from aapl.events where relevance_rule <> 'reject';
```

Save as `events.csv` and pass it to `scripts/run_real.py --events` in Grid_Feature_Engineering.

## Database

`supabase/migrations/` holds the schema. The `aapl` schema is not exposed through the API; the dashboard reads only the `public.aapl_*` views, and writes go through `aapl_*` RPC functions that only the service role can execute.
