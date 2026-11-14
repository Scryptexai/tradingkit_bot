-- Centralized retry schedule; workers ask the DB to assign jitter rather than sleeping independently.
alter table public.backtest_jobs add column if not exists next_attempt_at timestamptz;
alter table public.backtest_jobs add column if not exists retry_delay_seconds integer;
create or replace function public.schedule_backtest_retry(p_job_id uuid,p_worker_id text,p_lease_token uuid,p_attempt integer,p_base_seconds integer default 1,p_cap_seconds integer default 300)
returns timestamptz language plpgsql security definer set search_path=public,pg_temp as $$
declare v_delay integer; v_next timestamptz;
begin
 if p_attempt<1 or p_base_seconds<1 or p_cap_seconds<p_base_seconds then raise exception 'invalid retry bounds'; end if;
 if not exists(select 1 from public.backtest_job_leases where job_id=p_job_id and worker_id=p_worker_id and lease_token=p_lease_token and lease_expires_at>now() for update) then raise exception 'valid job lease required'; end if;
 v_delay:=least(p_cap_seconds, p_base_seconds * (2 ^ least(p_attempt-1,16))::integer);
 v_delay:=floor(v_delay * (0.5 + random()))::integer;
 v_next:=now()+make_interval(secs=>v_delay);
 update public.backtest_jobs set next_attempt_at=v_next,retry_delay_seconds=v_delay,status='retrying',updated_at=now() where id=p_job_id;
 delete from public.backtest_job_leases where job_id=p_job_id and lease_token=p_lease_token;
 return v_next;
end $$;
revoke all on function public.schedule_backtest_retry(uuid,text,uuid,integer,integer,integer) from public,anon,authenticated;
grant execute on function public.schedule_backtest_retry(uuid,text,uuid,integer,integer,integer) to service_role;
