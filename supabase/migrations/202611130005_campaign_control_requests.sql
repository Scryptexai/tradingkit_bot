-- User-triggered control intents are durable, but only a trusted local worker may acknowledge/execute them.
create table if not exists public.campaign_control_requests (
 id uuid primary key default gen_random_uuid(), user_id uuid not null references auth.users(id) on delete cascade,
 campaign_id uuid not null references public.campaigns(id) on delete cascade, command text not null check(command in ('pause','resume','stop','retry_failed')),
 job_ids uuid[] not null default '{}', request_key text not null, status text not null default 'pending_worker',
 result jsonb, created_at timestamptz not null default now(), expires_at timestamptz not null default now()+interval '15 minutes', handled_at timestamptz,
 unique(user_id,request_key), unique(user_id,id),
 foreign key(user_id,campaign_id) references public.campaigns(user_id,id)
);
alter table public.campaign_control_requests enable row level security;
create policy campaign_control_requests_owner_read on public.campaign_control_requests for select to authenticated using(user_id=auth.uid());
create policy campaign_control_requests_owner_insert on public.campaign_control_requests for insert to authenticated with check(user_id=auth.uid());
revoke update,delete on public.campaign_control_requests from authenticated;
grant select,insert on public.campaign_control_requests to authenticated;
create index if not exists control_requests_pending on public.campaign_control_requests(user_id,status,expires_at);
