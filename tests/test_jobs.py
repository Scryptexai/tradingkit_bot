import sqlite3
import pytest
from app.migrations import apply
from app.jobs import JobLedger

def test_atomic_job_lease_and_jittered_retry_schedule(tmp_path):
    c=sqlite3.connect(':memory:',timeout=5,isolation_level=None); c.row_factory=sqlite3.Row
    c.execute('CREATE TABLE strategies(id TEXT PRIMARY KEY,name TEXT,family TEXT,version INTEGER,market TEXT,timeframe TEXT,direction TEXT,parameters TEXT,rules TEXT,source TEXT,source_hash TEXT UNIQUE,created_at TEXT,status TEXT)')
    c.execute('CREATE TABLE campaigns(id TEXT PRIMARY KEY,name TEXT,market TEXT,status TEXT,total INTEGER,created_at TEXT)')
    c.execute('CREATE TABLE events(id TEXT PRIMARY KEY,campaign_id TEXT,type TEXT,status TEXT,description TEXT,created_at TEXT)')
    from app.report_store import init_report_tables
    init_report_tables(c); apply(c); ledger=JobLedger(c)
    job,_=ledger.create(campaign_id='c',strategy_id='s',strategy_version_id='v',idempotency_key='lease-key',source='source',parameters={},market='M',timeframe='1h')
    lease=ledger.claim('worker-a'); assert lease and lease['id']==job['id'] and lease['lease_token']
    assert ledger.claim('worker-b') is None
    assert ledger.renew_lease(job['id'],'worker-a',lease['lease_token'])
    import pytest
    with pytest.raises(RuntimeError,match='active lease'):
        ledger.schedule_retry(job['id'],'worker-b',lease['lease_token'],1,rng=lambda:0)
    due=ledger.schedule_retry(job['id'],'worker-a',lease['lease_token'],2,base_seconds=10,cap_seconds=60,rng=lambda:0)
    assert c.execute('select status,retry_delay_seconds,next_attempt_at from backtest_jobs').fetchone()[:2]==('retrying',10)
    assert c.execute('select count(*) from backtest_job_leases').fetchone()[0]==0
    assert due

def test_job_snapshot_idempotency_state_and_report_gate(tmp_path):
    db=tmp_path/'jobs.db'; c=sqlite3.connect(db); c.row_factory=sqlite3.Row
    c.execute('CREATE TABLE strategies(id TEXT PRIMARY KEY,name TEXT,family TEXT,version INTEGER,market TEXT,timeframe TEXT,direction TEXT,parameters TEXT,rules TEXT,source TEXT,source_hash TEXT UNIQUE,created_at TEXT,status TEXT)')
    c.execute('CREATE TABLE campaigns(id TEXT PRIMARY KEY,name TEXT,market TEXT,status TEXT,total INTEGER,created_at TEXT)')
    c.execute('CREATE TABLE events(id TEXT PRIMARY KEY,campaign_id TEXT,type TEXT,status TEXT,description TEXT,created_at TEXT)')
    from app.report_store import init_report_tables
    init_report_tables(c); apply(c)
    ledger=JobLedger(c)
    kwargs=dict(campaign_id='c',strategy_id='s',strategy_version_id='sv1',idempotency_key='stable-1',source='pine original',parameters={'len':12},market='BTCUSDT',timeframe='1h')
    job,new=ledger.create(**kwargs); assert new
    again,new=ledger.create(**{**kwargs,'source':'should not overwrite'})
    assert not new and again['source_snapshot']=='pine original'
    with pytest.raises(ValueError): ledger.finish_after_report_validation(job['id'],'report',False)
    ledger.transition(job['id'],'compilation_started');ledger.transition(job['id'],'compiled');ledger.transition(job['id'],'submitted',external_job_id='remote')
    ledger.transition(job['id'],'accepted');ledger.transition(job['id'],'running');ledger.transition(job['id'],'report_retrieval_started');ledger.transition(job['id'],'report_retrieved',external_report_id='report')
    ledger.finish_after_report_validation(job['id'],'report',True)
    c.close(); c=sqlite3.connect(db); assert c.execute('select status from backtest_jobs').fetchone()[0]=='completed'
