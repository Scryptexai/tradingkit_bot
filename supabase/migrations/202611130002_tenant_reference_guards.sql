-- Composite foreign keys enforce tenant ownership across references, beyond row-level filtering.
alter table public.strategies add constraint strategies_user_id_id_unique unique(user_id,id);
alter table public.campaigns add constraint campaigns_user_id_id_unique unique(user_id,id);
alter table public.strategy_versions add constraint strategy_versions_user_id_id_unique unique(user_id,id);
alter table public.backtest_jobs add constraint backtest_jobs_user_id_id_unique unique(user_id,id);
alter table public.reports add constraint reports_user_id_id_unique unique(user_id,id);
-- strategy_versions has its own user_id and strategy_id; reject cross-owner strategy references.
alter table public.strategy_versions add constraint strategy_version_strategy_owner foreign key(user_id,strategy_id) references public.strategies(user_id,id) not valid;
alter table public.backtest_jobs add constraint job_campaign_owner foreign key(user_id,campaign_id) references public.campaigns(user_id,id) not valid;
alter table public.backtest_jobs add constraint job_strategy_owner foreign key(user_id,strategy_id) references public.strategies(user_id,id) not valid;
alter table public.backtest_jobs add constraint job_version_owner foreign key(user_id,strategy_version_id) references public.strategy_versions(user_id,id) not valid;
alter table public.job_events add constraint event_job_owner foreign key(user_id,job_id) references public.backtest_jobs(user_id,id) not valid;
alter table public.reports add constraint report_strategy_owner foreign key(user_id,strategy_id) references public.strategies(user_id,id) not valid;
alter table public.reports add constraint report_job_owner foreign key(user_id,job_id) references public.backtest_jobs(user_id,id) not valid;
alter table public.trades add constraint trade_report_owner foreign key(user_id,report_id) references public.reports(user_id,id) not valid;
alter table public.optimizations add constraint optimization_strategy_owner foreign key(user_id,strategy_id) references public.strategies(user_id,id) not valid;
alter table public.optimizations add constraint optimization_campaign_owner foreign key(user_id,campaign_id) references public.campaigns(user_id,id) not valid;
alter table public.validations add constraint validation_strategy_owner foreign key(user_id,strategy_id) references public.strategies(user_id,id) not valid;
alter table public.validations add constraint validation_report_owner foreign key(user_id,report_id) references public.reports(user_id,id) not valid;
alter table public.strategy_knowledge add constraint knowledge_strategy_owner foreign key(user_id,strategy_id) references public.strategies(user_id,id) not valid;
-- Validate constraints after adding them; project is initially empty.
alter table public.strategy_versions validate constraint strategy_version_strategy_owner;
alter table public.backtest_jobs validate constraint job_campaign_owner;
alter table public.backtest_jobs validate constraint job_strategy_owner;
alter table public.backtest_jobs validate constraint job_version_owner;
alter table public.job_events validate constraint event_job_owner;
alter table public.reports validate constraint report_strategy_owner;
alter table public.reports validate constraint report_job_owner;
alter table public.trades validate constraint trade_report_owner;
alter table public.optimizations validate constraint optimization_strategy_owner;
alter table public.optimizations validate constraint optimization_campaign_owner;
alter table public.validations validate constraint validation_strategy_owner;
alter table public.validations validate constraint validation_report_owner;
alter table public.strategy_knowledge validate constraint knowledge_strategy_owner;
