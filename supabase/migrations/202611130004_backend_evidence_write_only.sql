-- Browser users can inspect execution evidence but cannot manufacture jobs, reports or events.
revoke insert, update, delete on public.backtest_jobs, public.job_events, public.reports, public.trades,
 public.worker_heartbeats, public.audit_logs, public.optimizations, public.validations, public.campaign_batches
 from authenticated;
grant select on public.backtest_jobs, public.job_events, public.reports, public.trades,
 public.worker_heartbeats, public.audit_logs, public.optimizations, public.validations, public.campaign_batches
 to authenticated;
