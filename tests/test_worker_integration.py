import asyncio, sqlite3
import pytest
from app.jobs import JobLedger
from app.migrations import apply
from app.report_store import init_report_tables
from app.execution_gate import GateState
from app.worker import CampaignWorker

class MockBacktestAdapter:
    def __init__(self,valid_source=True): self.submissions=0; self.reports=0; self.valid_source=valid_source
    async def compile(self,source): return self.valid_source and '@version=6' in source
    async def submit(self,**request): self.submissions+=1; return {'job_id':'mock-job-1'}
    async def wait(self,job_id): return 'completed'
    async def report(self,job_id):
        self.reports+=1; return {'report_id':'mock-report-1','source_hash':'h','trades':[]}
    async def validate_report(self,report,job): return report['source_hash']==job.get('source_hash','h')

def create_job():
    c=sqlite3.connect(':memory:');c.row_factory=sqlite3.Row
    c.execute('CREATE TABLE strategies(id TEXT PRIMARY KEY,name TEXT,family TEXT,version INTEGER,market TEXT,timeframe TEXT,direction TEXT,parameters TEXT,rules TEXT,source TEXT,source_hash TEXT UNIQUE,created_at TEXT,status TEXT)')
    c.execute('CREATE TABLE campaigns(id TEXT PRIMARY KEY,name TEXT,market TEXT,status TEXT,total INTEGER,created_at TEXT)')
    c.execute('CREATE TABLE events(id TEXT PRIMARY KEY,campaign_id TEXT,type TEXT,status TEXT,description TEXT,created_at TEXT)')
    init_report_tables(c);apply(c);ledger=JobLedger(c)
    job,_=ledger.create(campaign_id='c',strategy_id='s',strategy_version_id='v1',idempotency_key='one',source='//@version=6',parameters={},market='BTCUSDT',timeframe='1h')
    job['source_hash']='h';return ledger,job

def test_worker_runs_complete_lifecycle_only_with_explicit_gate():
    async def go():
        ledger,job=create_job();adapter=MockBacktestAdapter();worker=CampaignWorker(ledger,adapter,max_concurrency=1,backoff_base=.001)
        with pytest.raises(PermissionError): await worker.run(job,gate=GateState())
        result=await worker.run(job,gate=GateState(True,True,True,True,True,True))
        assert result=={'status':'completed','report_id':'mock-report-1'}
        assert adapter.submissions==1
        assert ledger.conn.execute('select status from backtest_jobs').fetchone()['status']=='completed'
        assert [r[0] for r in ledger.conn.execute('select event_type from job_events')][-1]=='completed'
        await worker.shutdown()
    asyncio.run(go())

def test_worker_recovers_persisted_external_job_without_resubmitting():
    async def go():
        ledger,job=create_job();adapter=MockBacktestAdapter();worker=CampaignWorker(ledger,adapter,max_concurrency=1,backoff_base=.001)
        for state,kwargs in [('compilation_started',{}),('compiled',{}),('submitted',{}),('accepted',{'external_job_id':'already-accepted'})]:ledger.transition(job['id'],state,**kwargs)
        results=await worker.recover_interrupted(gate=GateState(True,True,True,True,True,True))
        assert results==[{'status':'completed','report_id':'mock-report-1'}]
        assert adapter.submissions==0
        assert ledger.conn.execute('select status from backtest_jobs').fetchone()['status']=='completed'
        await worker.shutdown()
    asyncio.run(go())

def test_worker_retries_then_dead_letters_failure_without_fabricating_success():
    async def go():
        ledger,job=create_job();worker=CampaignWorker(ledger,MockBacktestAdapter(False),max_concurrency=1,max_retries=1,backoff_base=.001)
        result=await worker.run(job,gate=GateState(True,True,True,True,True,True))
        assert result['status']=='dead_letter' and result['error_class']=='source_validation'
        row=ledger.conn.execute('select status,attempt from backtest_jobs').fetchone()
        assert row['status']=='dead_letter' and row['attempt']==2
        assert ledger.conn.execute('select count(*) from job_events where event_type="retrying"').fetchone()[0]==1
    asyncio.run(go())
