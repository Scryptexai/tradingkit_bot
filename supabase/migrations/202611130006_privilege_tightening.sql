-- Remove inherited broad/default ACLs, then grant only the browser permissions actually used.
revoke all on public.backtest_jobs, public.job_events, public.reports, public.trades,
 public.worker_heartbeats, public.audit_logs, public.optimizations, public.validations, public.campaign_batches
 from authenticated;
grant select on public.backtest_jobs, public.job_events, public.reports, public.trades,
 public.worker_heartbeats, public.audit_logs, public.optimizations, public.validations, public.campaign_batches
 to authenticated;
revoke all on public.campaign_control_requests from authenticated;
grant select,insert on public.campaign_control_requests to authenticated;
