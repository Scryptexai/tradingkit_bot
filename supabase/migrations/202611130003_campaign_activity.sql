-- Persist real orchestration batches and richer execution/event clocks.
create table if not exists public.campaign_batches (
 id uuid primary key default gen_random_uuid(), user_id uuid not null references auth.users(id) on delete cascade,
 campaign_id uuid not null references public.campaigns(id) on delete cascade,
 batch_number integer not null, status text not null default 'queued', total_jobs integer not null default 0,
 started_at timestamptz, finished_at timestamptz, created_at timestamptz not null default now(),
 unique(campaign_id,batch_number), unique(user_id,id),
 foreign key(user_id,campaign_id) references public.campaigns(user_id,id)
);
alter table public.backtest_jobs add column if not exists batch_id uuid;
alter table public.backtest_jobs add column if not exists worker_id text;
alter table public.backtest_jobs add column if not exists started_at timestamptz;
alter table public.backtest_jobs add column if not exists finished_at timestamptz;
alter table public.backtest_jobs add column if not exists duration_ms bigint;
alter table public.backtest_jobs add column if not exists heartbeat_at timestamptz;
alter table public.backtest_jobs add column if not exists retry_after timestamptz;
alter table public.backtest_jobs add constraint job_batch_owner foreign key(user_id,batch_id) references public.campaign_batches(user_id,id) not valid;
alter table public.backtest_jobs validate constraint job_batch_owner;
alter table public.job_events add column if not exists strategy_id uuid;
alter table public.job_events add column if not exists batch_id uuid;
alter table public.job_events add column if not exists duration_ms bigint;
alter table public.job_events add constraint event_strategy_owner foreign key(user_id,strategy_id) references public.strategies(user_id,id) not valid;
alter table public.job_events add constraint event_batch_owner foreign key(user_id,batch_id) references public.campaign_batches(user_id,id) not valid;
alter table public.job_events validate constraint event_strategy_owner;
alter table public.job_events validate constraint event_batch_owner;
alter table public.campaigns add constraint campaign_status_allowed check(status in ('draft','queued','running','paused','stopped','completed','failed')) not valid;
alter table public.campaigns validate constraint campaign_status_allowed;
alter table public.campaign_batches enable row level security;
create policy campaign_batches_owner_all on public.campaign_batches for all to authenticated using(user_id=auth.uid()) with check(user_id=auth.uid());
grant select,insert,update,delete on public.campaign_batches to authenticated;
create index if not exists campaign_batches_owner on public.campaign_batches(user_id,campaign_id,batch_number);
create index if not exists jobs_owner_retry on public.backtest_jobs(user_id,status,retry_after);
create index if not exists job_events_owner_created on public.job_events(user_id,created_at desc);
do $$ begin
 if exists(select 1 from pg_publication where pubname='supabase_realtime')
    and not exists(select 1 from pg_publication_tables where pubname='supabase_realtime' and schemaname='public' and tablename='job_events') then
   alter publication supabase_realtime add table public.job_events;
 end if;
end $$;
