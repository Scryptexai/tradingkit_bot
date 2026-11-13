import sqlite3
import pytest
from app.migrations import apply
from app.jobs import JobLedger

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
