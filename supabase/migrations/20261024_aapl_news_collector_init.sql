-- Applied to the Supabase project on 2026-10-24 as migration "aapl_news_collector_init".
-- Everything lives in schema aapl; public only gets read views and service-role-only RPCs.
create schema if not exists aapl;

create table aapl.runs (
  run_id text primary key,
  query_version text not null,
  started_at_utc timestamptz not null,
  finished_at_utc timestamptz,
  status text not null default 'running',
  sources jsonb not null default '{}'::jsonb,
  n_returned int default 0,
  n_new int default 0,
  n_duplicate int default 0,
  n_labeled int default 0,
  error text
);

create table aapl.events (
  idempotency_key text primary key,
  source text not null,
  source_record_id text,
  published_at_utc timestamptz,
  first_seen_at_utc timestamptz not null,
  available_at_utc timestamptz not null,
  availability_basis text not null,
  ingestion_run_id text not null references aapl.runs(run_id),
  query_version text not null,
  url text,
  canonical_url text,
  title text not null default '',
  text_raw text not null default '',
  source_domain text,
  language text,
  raw_payload jsonb,
  content_hash text not null,
  relevance_rule text not null check (relevance_rule in ('primary','strong','weak','reject')),
  audit_issues text not null default '',
  needs_agent_review boolean not null default false,
  -- labels written by the review agent; raw fields above are never updated
  is_apple_company boolean,
  event_type text,
  sentiment real check (sentiment between -1 and 1),
  sentiment_basis text,
  novelty text,
  label_confidence real,
  label_model text,
  label_prompt_version text,
  labeled_at_utc timestamptz,
  label_is_retrospective boolean,
  inserted_at timestamptz not null default now()
);
create index on aapl.events (available_at_utc desc);
create index on aapl.events (content_hash);
create index on aapl.events (source, available_at_utc desc);
create index on aapl.events (labeled_at_utc) where labeled_at_utc is null;
create index on aapl.events (ingestion_run_id);

alter table aapl.runs enable row level security;
alter table aapl.events enable row level security;

-- News is public information: dashboard (anon) may read, never write.
grant usage on schema aapl to anon, authenticated;
grant select on aapl.runs, aapl.events to anon, authenticated;
create policy aapl_runs_read on aapl.runs for select to anon, authenticated using (true);
create policy aapl_events_read on aapl.events for select to anon, authenticated using (true);

-- Read views in public (aapl schema is not exposed through the API).
create view public.aapl_feed with (security_invoker = true) as
  select idempotency_key, source, source_domain, title, url, published_at_utc, available_at_utc,
         availability_basis, relevance_rule, content_hash, event_type, sentiment, novelty,
         label_confidence, is_apple_company
  from aapl.events
  where relevance_rule <> 'reject'
  order by available_at_utc desc
  limit 1000;

create view public.aapl_daily with (security_invoker = true) as
  select (available_at_utc at time zone 'America/New_York')::date as ny_date,
         count(*) filter (where relevance_rule <> 'reject') as items,
         count(distinct content_hash) filter (where relevance_rule <> 'reject') as stories,
         count(*) filter (where relevance_rule = 'primary') as primary_items,
         count(*) filter (where relevance_rule = 'reject') as rejected,
         round(avg(sentiment)::numeric, 3) as avg_sentiment,
         count(*) filter (where sentiment < -0.2) as negative_items
  from aapl.events
  group by 1
  order by 1 desc;

create view public.aapl_source_mix with (security_invoker = true) as
  select source, relevance_rule, count(*) as items, max(available_at_utc) as latest
  from aapl.events group by 1, 2;

create view public.aapl_runs_recent with (security_invoker = true) as
  select run_id, query_version, started_at_utc, finished_at_utc, status, sources,
         n_returned, n_new, n_duplicate, n_labeled, error
  from aapl.runs order by started_at_utc desc limit 200;

grant select on public.aapl_feed, public.aapl_daily, public.aapl_source_mix, public.aapl_runs_recent to anon, authenticated;

-- Write path: service_role only, via RPC.
create or replace function public.aapl_start_run(run jsonb) returns void
language plpgsql security definer set search_path = '' as $$
begin
  insert into aapl.runs (run_id, query_version, started_at_utc)
  values (run->>'run_id', run->>'query_version', (run->>'started_at_utc')::timestamptz)
  on conflict (run_id) do nothing;
end $$;

create or replace function public.aapl_ingest_events(rows jsonb)
returns table (inserted int, duplicates int)
language plpgsql security definer set search_path = '' as $$
declare n_in int; n_new int;
begin
  n_in := jsonb_array_length(rows);
  with ins as (
    insert into aapl.events (idempotency_key, source, source_record_id, published_at_utc, first_seen_at_utc,
      available_at_utc, availability_basis, ingestion_run_id, query_version, url, canonical_url, title, text_raw,
      source_domain, language, raw_payload, content_hash, relevance_rule, audit_issues, needs_agent_review)
    select r->>'idempotency_key', r->>'source', r->>'source_record_id', (r->>'published_at_utc')::timestamptz,
      (r->>'first_seen_at_utc')::timestamptz, (r->>'available_at_utc')::timestamptz, r->>'availability_basis',
      r->>'ingestion_run_id', r->>'query_version', r->>'url', r->>'canonical_url', coalesce(r->>'title',''),
      coalesce(r->>'text_raw',''), r->>'source_domain', r->>'language', r->'raw_payload', r->>'content_hash',
      r->>'relevance_rule', coalesce(r->>'audit_issues',''), coalesce((r->>'needs_agent_review')::boolean,false)
    from jsonb_array_elements(rows) r
    on conflict (idempotency_key) do nothing   -- keep the FIRST observation
    returning 1)
  select count(*) into n_new from ins;
  return query select n_new, n_in - n_new;
end $$;

create or replace function public.aapl_finish_run(run jsonb) returns void
language plpgsql security definer set search_path = '' as $$
begin
  update aapl.runs set
    finished_at_utc = (run->>'finished_at_utc')::timestamptz,
    status = run->>'status',
    sources = coalesce(run->'sources','{}'::jsonb),
    n_returned = coalesce((run->>'n_returned')::int,0),
    n_new = coalesce((run->>'n_new')::int,0),
    n_duplicate = coalesce((run->>'n_duplicate')::int,0),
    n_labeled = coalesce((run->>'n_labeled')::int,0),
    error = run->>'error'
  where run_id = run->>'run_id';
end $$;

create or replace function public.aapl_unlabeled(max_rows int default 40)
returns table (idempotency_key text, source text, title text, text_raw text, relevance_rule text, published_at_utc timestamptz)
language sql security definer set search_path = '' as $$
  select e.idempotency_key, e.source, e.title, left(e.text_raw, 1500), e.relevance_rule, e.published_at_utc
  from aapl.events e
  where e.labeled_at_utc is null and e.relevance_rule in ('primary','strong','weak')
  order by e.available_at_utc desc
  limit max_rows;
$$;

create or replace function public.aapl_set_labels(rows jsonb) returns int
language plpgsql security definer set search_path = '' as $$
declare n int;
begin
  update aapl.events e set
    is_apple_company = (r->>'is_apple_company')::boolean,
    event_type = r->>'event_type',
    sentiment = greatest(-1, least(1, (r->>'sentiment')::real)),
    sentiment_basis = r->>'sentiment_basis',
    novelty = r->>'novelty',
    label_confidence = (r->>'confidence')::real,
    label_model = r->>'label_model',
    label_prompt_version = r->>'label_prompt_version',
    labeled_at_utc = now(),
    label_is_retrospective = now() - coalesce(e.published_at_utc, e.first_seen_at_utc) > interval '24 hours'
  from jsonb_array_elements(rows) r
  where e.idempotency_key = r->>'idempotency_key' and e.labeled_at_utc is null;
  get diagnostics n = row_count;
  return n;
end $$;

revoke all on function public.aapl_start_run(jsonb), public.aapl_ingest_events(jsonb), public.aapl_finish_run(jsonb),
  public.aapl_unlabeled(int), public.aapl_set_labels(jsonb) from public, anon, authenticated;
grant execute on function public.aapl_start_run(jsonb), public.aapl_ingest_events(jsonb), public.aapl_finish_run(jsonb),
  public.aapl_unlabeled(int), public.aapl_set_labels(jsonb) to service_role;
