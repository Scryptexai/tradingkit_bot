-- User-scoped research data. No TradingKit tokens or exchange credentials are stored here.
create extension if not exists pgcrypto;
create table if not exists public.profiles (
  id uuid primary key references auth.users(id) on delete cascade,
  display_name text, created_at timestamptz not null default now()
);
create table if not exists public.connections (
  id uuid primary key default gen_random_uuid(), user_id uuid not null references auth.users(id) on delete cascade,
  provider text not null, status text not null default 'not_connected', auth_status text not null default 'not_verified',
  account_ref text, capabilities jsonb, checked_at timestamptz, metadata jsonb not null default '{}',
  created_at timestamptz not null default now(), updated_at timestamptz not null default now(), unique(user_id,provider)
);
create table if not exists public.strategies (
  id uuid primary key default gen_random_uuid(), user_id uuid not null references auth.users(id) on delete cascade,
  name text not null, family text not null, version integer not null default 1, market text not null, timeframe text not null,
  direction text not null default 'Both', parameters jsonb not null default '{}', rules jsonb not null default '{}',
  source text not null, source_hash text not null, status text not null default 'generated', created_at timestamptz not null default now(),
  unique(user_id,source_hash)
);
create table if not exists public.strategy_versions (
  id uuid primary key default gen_random_uuid(), user_id uuid not null references auth.users(id) on delete cascade,
  strategy_id uuid not null references public.strategies(id) on delete cascade, version integer not null,
  source text not null, source_hash text not null, parameters jsonb not null, rules jsonb not null, created_at timestamptz not null default now(),
  unique(strategy_id,version)
);
create table if not exists public.campaigns (
  id uuid primary key default gen_random_uuid(), user_id uuid not null references auth.users(id) on delete cascade,
  name text not null, market text not null, timeframe text, status text not null default 'draft', total_candidates integer not null default 0,
  settings jsonb not null default '{}', created_at timestamptz not null default now(), updated_at timestamptz not null default now()
);
create table if not exists public.backtest_jobs (
  id uuid primary key default gen_random_uuid(), user_id uuid not null references auth.users(id) on delete cascade,
  campaign_id uuid not null references public.campaigns(id) on delete cascade, strategy_id uuid not null references public.strategies(id),
  strategy_version_id uuid references public.strategy_versions(id), status text not null default 'generated',
  idempotency_key text not null, source_snapshot text not null, parameters_snapshot jsonb not null,
  market text not null, timeframe text not null, attempt integer not null default 0, max_attempts integer not null default 3,
  timeout_seconds integer not null default 900, external_job_id text, external_report_id text,
  error_class text, error_message text, created_at timestamptz not null default now(), updated_at timestamptz not null default now(),
  unique(user_id,idempotency_key)
);
create table if not exists public.job_events (
  id uuid primary key default gen_random_uuid(), user_id uuid not null references auth.users(id) on delete cascade,
  job_id uuid not null references public.backtest_jobs(id) on delete cascade, event_type text not null,
  status text not null, payload jsonb not null default '{}', created_at timestamptz not null default now()
);
create table if not exists public.reports (
  id uuid primary key default gen_random_uuid(), user_id uuid not null references auth.users(id) on delete cascade,
  strategy_id uuid not null references public.strategies(id), job_id uuid references public.backtest_jobs(id),
  adapter text not null, external_job_id text not null, external_report_id text not null, source_hash text not null,
  market text not null, timeframe text not null, assumptions jsonb not null default '{}', metrics jsonb not null,
  returned_at timestamptz not null default now(), unique(user_id,adapter,external_report_id)
);
create table if not exists public.trades (
  id bigint generated always as identity primary key, user_id uuid not null references auth.users(id) on delete cascade,
  report_id uuid not null references public.reports(id) on delete cascade, trade_index integer not null,
  side text not null, pnl numeric not null, fees numeric not null default 0, funding numeric not null default 0,
  slippage numeric not null default 0, entry_time timestamptz, exit_time timestamptz,
  entry_price numeric, exit_price numeric, quantity numeric, notional numeric, risk_amount numeric,
  regime text, raw jsonb not null default '{}', unique(report_id,trade_index)
);
create table if not exists public.optimizations (
  id uuid primary key default gen_random_uuid(), user_id uuid not null references auth.users(id) on delete cascade,
  campaign_id uuid references public.campaigns(id) on delete set null, strategy_id uuid not null references public.strategies(id),
  method text not null, status text not null, config jsonb not null, results jsonb, created_at timestamptz not null default now()
);
create table if not exists public.validations (
  id uuid primary key default gen_random_uuid(), user_id uuid not null references auth.users(id) on delete cascade,
  strategy_id uuid not null references public.strategies(id), report_id uuid references public.reports(id), method text not null,
  status text not null, plan jsonb not null, result jsonb, created_at timestamptz not null default now()
);
create table if not exists public.worker_heartbeats (
  worker_id text primary key, user_id uuid not null references auth.users(id) on delete cascade,
  status text not null, capabilities jsonb not null default '{}', seen_at timestamptz not null default now()
);
create table if not exists public.audit_logs (
  id bigint generated always as identity primary key, user_id uuid not null references auth.users(id) on delete cascade,
  action text not null, entity_type text, entity_id text, details jsonb not null default '{}', created_at timestamptz not null default now()
);
create table if not exists public.strategy_knowledge (
  id uuid primary key default gen_random_uuid(), user_id uuid not null references auth.users(id) on delete cascade,
  strategy_id uuid references public.strategies(id) on delete set null, kind text not null, content jsonb not null,
  evidence_report_ids uuid[] not null default '{}', created_at timestamptz not null default now()
);
create index if not exists strategies_owner_family on public.strategies(user_id,family,market,timeframe);
create index if not exists campaigns_owner_created on public.campaigns(user_id,created_at desc);
create index if not exists jobs_owner_campaign_status on public.backtest_jobs(user_id,campaign_id,status);
create index if not exists reports_owner_strategy on public.reports(user_id,strategy_id,returned_at desc);
create index if not exists trades_report_order on public.trades(report_id,trade_index);
create index if not exists knowledge_owner_kind on public.strategy_knowledge(user_id,kind,created_at desc);
-- RLS: every row is isolated to the authenticated user. The browser uses only the publishable key.
do $$ declare t text; begin
 foreach t in array array['connections','strategies','strategy_versions','campaigns','backtest_jobs','job_events','reports','trades','optimizations','validations','worker_heartbeats','audit_logs','strategy_knowledge'] loop
  execute format('alter table public.%I enable row level security',t);
  execute format('create policy %I on public.%I for all to authenticated using (user_id = auth.uid()) with check (user_id = auth.uid())',t||'_owner_all',t);
 end loop;
 alter table public.profiles enable row level security;
 create policy profiles_owner_all on public.profiles for all to authenticated using (id = auth.uid()) with check (id = auth.uid());
end $$;
grant select,insert,update,delete on public.profiles,public.connections,public.strategies,public.strategy_versions,public.campaigns,public.backtest_jobs,public.job_events,public.reports,public.trades,public.optimizations,public.validations,public.worker_heartbeats,public.audit_logs,public.strategy_knowledge to authenticated;
grant usage,select on all sequences in schema public to authenticated;
