-- Execution reproducibility and persistent worker leases. Server-owned tables only.
alter table public.backtest_jobs add column if not exists source_hash text;
alter table public.backtest_jobs add column if not exists interval_start timestamptz;
alter table public.backtest_jobs add column if not exists interval_end timestamptz;
alter table public.backtest_jobs add column if not exists submitted_at timestamptz;
alter table public.backtest_jobs add column if not exists started_at timestamptz;
alter table public.backtest_jobs add column if not exists finished_at timestamptz;
alter table public.backtest_jobs add column if not exists next_attempt_at timestamptz;
alter table public.backtest_jobs add column if not exists retry_delay_seconds integer;
alter table public.reports add column if not exists strategy_version_id uuid references public.strategy_versions(id);
alter table public.reports add column if not exists interval_start timestamptz;
alter table public.reports add column if not exists interval_end timestamptz;
alter table public.reports add column if not exists parameters_snapshot jsonb;
alter table public.reports add column if not exists execution_started_at timestamptz;
alter table public.reports add column if not exists execution_completed_at timestamptz;
alter table public.reports add column if not exists cost_assumptions jsonb;
alter table public.reports add column if not exists provider_metrics jsonb;
alter table public.reports add column if not exists unavailable_fields jsonb not null default '[]'::jsonb;
alter table public.reports add column if not exists actual_trade_count integer;
create index if not exists reports_owner_job on public.reports(user_id,job_id);
create index if not exists jobs_owner_source_hash on public.backtest_jobs(user_id,source_hash);
create table if not exists public.backtest_job_leases(
 job_id uuid primary key references public.backtest_jobs(id) on delete cascade,
 worker_id text not null,
 lease_token uuid not null unique,
 lease_expires_at timestamptz not null,
 claimed_at timestamptz not null default now(),
 updated_at timestamptz not null default now()
);
alter table public.backtest_job_leases enable row level security;
revoke all on public.backtest_job_leases from anon,authenticated;
revoke all on public.backtest_job_leases from public;
grant select,insert,update,delete on public.backtest_job_leases to service_role;
create or replace function public.claim_backtest_job(p_worker_id text,p_lease_seconds integer default 120)
returns setof public.backtest_jobs language plpgsql security definer set search_path=public,pg_temp as $$
declare v_job_id uuid; v_token uuid:=gen_random_uuid();
begin
 if p_worker_id is null or length(trim(p_worker_id))=0 or p_lease_seconds not between 10 and 3600 then raise exception 'invalid worker or lease'; end if;
 select j.id into v_job_id from public.backtest_jobs j
 where j.status not in ('completed','dead_letter') and (j.next_attempt_at is null or j.next_attempt_at<=now())
 and not exists(select 1 from public.backtest_job_leases l where l.job_id=j.id and l.lease_expires_at>now())
 order by j.created_at for update of j skip locked limit 1;
 if v_job_id is null then return; end if;
 insert into public.backtest_job_leases(job_id,worker_id,lease_token,lease_expires_at)
 values(v_job_id,p_worker_id,v_token,now()+make_interval(secs=>p_lease_seconds))
 on conflict(job_id) do update set worker_id=excluded.worker_id,lease_token=excluded.lease_token,lease_expires_at=excluded.lease_expires_at,updated_at=now();
 return query select * from public.backtest_jobs where id=v_job_id;
end $$;
revoke all on function public.claim_backtest_job(text,integer) from public,anon,authenticated;
grant execute on function public.claim_backtest_job(text,integer) to service_role;
