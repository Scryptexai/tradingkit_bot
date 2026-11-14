import asyncio, hashlib, json, sqlite3
import pytest
from app.jobs import JobLedger
from app.migrations import apply
from app.report_store import init_report_tables
from app.execution_gate import GateState
from app.worker import CampaignWorker, VerifiedProviderLimits

MOCK_LIMITS=VerifiedProviderLimits(max_concurrency=1,requests_per_second=1000,evidence_reference='mock adapter test fixture; not provider evidence',verified=True)

def test_worker_requires_explicit_verified_provider_limits_and_enforces_ceiling():
    ledger,_=create_job(); adapter=MockBacktestAdapter()
    with pytest.raises(ValueError,match='verified against authoritative'):
        CampaignWorker(ledger,adapter,max_concurrency=1,provider_limits=VerifiedProviderLimits(1,1,'',False))
    with pytest.raises(ValueError,match='exceeds verified provider limit'):
        CampaignWorker(ledger,adapter,max_concurrency=2,provider_limits=MOCK_LIMITS)

class MockBacktestAdapter:
    def __init__(self,valid_source=True): self.submissions=0; self.reports=0; self.valid_source=valid_source; self.source_hash=hashlib.sha256('//@version=6'.encode()).hexdigest()
    async def compile(self,source): return self.valid_source and '@version=6' in source
    async def submit(self,**request): self.submissions+=1; return {'job_id':'mock-job-1'}
    async def wait(self,job_id): return 'completed'
    async def report(self,job_id):
        self.reports+=1; return {'report_id':'mock-report-1','source_hash':self.source_hash,'trades':[]}
    async def validate_report(self,report,job): return report['source_hash']==job.get('source_hash','h')

def create_job():
    c=sqlite3.connect(':memory:');c.row_factory=sqlite3.Row
    c.execute('CREATE TABLE strategies(id TEXT PRIMARY KEY,name TEXT,family TEXT,version INTEGER,market TEXT,timeframe TEXT,direction TEXT,parameters TEXT,rules TEXT,source TEXT,source_hash TEXT UNIQUE,created_at TEXT,status TEXT)')
    c.execute('CREATE TABLE campaigns(id TEXT PRIMARY KEY,name TEXT,market TEXT,status TEXT,total INTEGER,created_at TEXT)')
    c.execute('CREATE TABLE events(id TEXT PRIMARY KEY,campaign_id TEXT,type TEXT,status TEXT,description TEXT,created_at TEXT)')
    init_report_tables(c);apply(c);ledger=JobLedger(c)
    job,_=ledger.create(campaign_id='c',strategy_id='s',strategy_version_id='v1',idempotency_key='one',source='//@version=6',parameters={},market='BTCUSDT',timeframe='1h')
    return ledger,job

def test_worker_runs_complete_lifecycle_only_with_explicit_gate():
    async def go():
        ledger,job=create_job();adapter=MockBacktestAdapter();worker=CampaignWorker(ledger,adapter,max_concurrency=1,provider_limits=MOCK_LIMITS,backoff_base=.001)
        with pytest.raises(PermissionError): await worker.run(job,gate=GateState())
        result=await worker.run(job,gate=GateState(True,True,True,True,True,True))
        assert result=={'status':'completed','report_id':'mock-report-1'}
        assert adapter.submissions==1
        assert ledger.conn.execute('select status from backtest_jobs').fetchone()['status']=='completed'
        assert [r[0] for r in ledger.conn.execute('select event_type from job_events')][-1]=='completed'
        report=ledger.conn.execute('select job_id,strategy_version_id,source_hash,parameters_json,provider_metrics_json,unavailable_fields_json,actual_trade_count from reports').fetchone()
        assert report['job_id']==job['id'] and report['strategy_version_id']=='v1'
        assert report['source_hash']==job['source_hash'] and json.loads(report['parameters_json'])=={}
        assert report['actual_trade_count']==0 and 'provider_metrics' in json.loads(report['unavailable_fields_json'])
        assert ledger.conn.execute('select status from worker_heartbeats where worker_id=?',(worker.worker_id,)).fetchone()['status']=='idle'
        await worker.shutdown()
    asyncio.run(go())

def test_worker_recovers_persisted_external_job_without_resubmitting():
    async def go():
        ledger,job=create_job();adapter=MockBacktestAdapter();worker=CampaignWorker(ledger,adapter,max_concurrency=1,provider_limits=MOCK_LIMITS,backoff_base=.001)
        for state,kwargs in [('compilation_started',{}),('compiled',{}),('submitted',{}),('accepted',{'external_job_id':'already-accepted'})]:ledger.transition(job['id'],state,**kwargs)
        results=await worker.recover_interrupted(gate=GateState(True,True,True,True,True,True))
        assert results==[{'status':'completed','report_id':'mock-report-1'}]
        assert adapter.submissions==0
        assert ledger.conn.execute('select status from backtest_jobs').fetchone()['status']=='completed'
        await worker.shutdown()
    asyncio.run(go())

def test_worker_recovers_submitted_job_with_external_id_without_duplicate_submit():
    async def go():
        ledger,job=create_job();adapter=MockBacktestAdapter();worker=CampaignWorker(ledger,adapter,max_concurrency=1,provider_limits=MOCK_LIMITS,backoff_base=.001)
        ledger.transition(job['id'],'compilation_started');ledger.transition(job['id'],'compiled');ledger.transition(job['id'],'submitted',external_job_id='submit-ack-was-persisted')
        result=await worker.recover_interrupted(gate=GateState(True,True,True,True,True,True))
        assert result==[{'status':'completed','report_id':'mock-report-1'}]
        assert adapter.submissions==0
    asyncio.run(go())

def test_worker_retries_persisted_provider_job_without_resubmitting_after_retrying_state():
    async def go():
        ledger,job=create_job();adapter=MockBacktestAdapter();worker=CampaignWorker(ledger,adapter,max_concurrency=1,provider_limits=MOCK_LIMITS,backoff_base=.001)
        for state,kwargs in [('compilation_started',{}),('compiled',{}),('submitted',{'external_job_id':'stable-provider-id'}),('accepted',{}),('running',{}),('failed',{'attempt':1}),('retrying',{'attempt':2})]:ledger.transition(job['id'],state,**kwargs)
        result=await worker.recover_interrupted(gate=GateState(True,True,True,True,True,True))
        assert result==[{'status':'completed','report_id':'mock-report-1'}]
        assert adapter.submissions==0
    asyncio.run(go())

def test_worker_retries_then_dead_letters_failure_without_fabricating_success():
    async def go():
        ledger,job=create_job();worker=CampaignWorker(ledger,MockBacktestAdapter(False),max_concurrency=1,provider_limits=MOCK_LIMITS,max_retries=1,backoff_base=.001)
        result=await worker.run(job,gate=GateState(True,True,True,True,True,True))
        assert result['status']=='retry_scheduled' and result['error_class']=='source_validation'
        row=ledger.conn.execute('select status,attempt,next_attempt_at,retry_delay_seconds from backtest_jobs').fetchone()
        assert row['status']=='retrying' and row['attempt']==1 and row['next_attempt_at'] and row['retry_delay_seconds']>=1
        assert ledger.conn.execute('select count(*) from job_events where event_type="retry_scheduled"').fetchone()[0]==1
        ledger.conn.execute("update backtest_jobs set next_attempt_at='2000-01-01T00:00:00+00:00' where id=?",(job['id'],)); ledger.conn.commit()
        result=await worker.run(job,gate=GateState(True,True,True,True,True,True))
        assert result['status']=='dead_letter' and result['error_class']=='source_validation'
        row=ledger.conn.execute('select status,attempt from backtest_jobs').fetchone()
        assert row['status']=='dead_letter' and row['attempt']==2
    asyncio.run(go())
