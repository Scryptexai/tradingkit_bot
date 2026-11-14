"""Durable idempotent job ledger and strict execution state machine."""
import hashlib, json, random, sqlite3, uuid
from datetime import datetime, timezone
from .execution_gate import GateState, check

TRANSITIONS={
 'generated':{'compilation_started'},'compilation_started':{'compiled','failed'},'compiled':{'submitted','failed'},
 'submitted':{'accepted','failed'},'accepted':{'running','report_retrieval_started','failed'},
 'running':{'report_retrieval_started','failed'},'report_retrieval_started':{'report_retrieved','failed'},
 'report_retrieved':{'completed','failed'},'failed':{'retrying','dead_letter'},'retrying':{'compilation_started','submitted','dead_letter'},
 'completed':set(),'dead_letter':set()
}
def stamp():return datetime.now(timezone.utc).isoformat()
class JobLedger:
    def __init__(self,conn:sqlite3.Connection): self.conn=conn; self.conn.row_factory=sqlite3.Row
    def create(self,*,campaign_id,strategy_id,strategy_version_id,idempotency_key,source,parameters,market,timeframe,source_hash=None,interval_start=None,interval_end=None,max_attempts=3,timeout_seconds=900):
        if not idempotency_key or len(idempotency_key)>128: raise ValueError('idempotency key required (max 128 chars)')
        jid=str(uuid.uuid4()); ts=stamp(); source_hash=hashlib.sha256(source.encode('utf-8')).hexdigest()
        if (interval_start is None)!=(interval_end is None): raise ValueError('both historical interval bounds are required together')
        if interval_start is not None and interval_start>=interval_end: raise ValueError('interval_start must precede interval_end')
        # Serialize idempotency lookup + insert so concurrent dispatchers cannot create
        # duplicate logical jobs. The unique DB constraint remains the final guard.
        try:
            with self.conn:
                existing=self.conn.execute('SELECT * FROM backtest_jobs WHERE idempotency_key=?',(idempotency_key,)).fetchone()
                if existing: return dict(existing),False
                self.conn.execute('INSERT INTO backtest_jobs(id,campaign_id,strategy_id,strategy_version_id,status,idempotency_key,source_snapshot,parameters_snapshot,market,timeframe,max_attempts,timeout_seconds,created_at,updated_at,source_hash,interval_start,interval_end) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',(jid,campaign_id,strategy_id,strategy_version_id,'generated',idempotency_key,source,json.dumps(parameters,sort_keys=True),market,timeframe,max_attempts,timeout_seconds,ts,ts,source_hash,interval_start,interval_end))
                self.event(jid,'strategy_generated','generated',{})
        except sqlite3.IntegrityError:
            existing=self.conn.execute('SELECT * FROM backtest_jobs WHERE idempotency_key=?',(idempotency_key,)).fetchone()
            if existing: return dict(existing),False
            raise
        return dict(self.conn.execute('SELECT * FROM backtest_jobs WHERE id=?',(jid,)).fetchone()),True
    def claim(self,worker_id,*,job_id=None,lease_seconds=120):
        """Atomically lease one due job. SQLite BEGIN IMMEDIATE serializes competing workers."""
        if not worker_id or not 10<=lease_seconds<=3600: raise ValueError('worker ID and lease duration 10..3600s required')
        token=str(uuid.uuid4()); now=stamp(); expiry=datetime.fromtimestamp(datetime.now(timezone.utc).timestamp()+lease_seconds,timezone.utc).isoformat()
        with self.conn:
            query="SELECT j.* FROM backtest_jobs j LEFT JOIN backtest_job_leases l ON l.job_id=j.id WHERE j.status NOT IN ('completed','dead_letter') AND (j.next_attempt_at IS NULL OR j.next_attempt_at<=?) AND (l.lease_expires_at IS NULL OR l.lease_expires_at<=?)"
            args=[now,now]
            if job_id is not None: query+=' AND j.id=?'; args.append(job_id)
            query+=' ORDER BY j.created_at LIMIT 1'
            row=self.conn.execute(query,args).fetchone()
            if not row: return None
            self.conn.execute("INSERT INTO backtest_job_leases(job_id,worker_id,lease_token,lease_expires_at,claimed_at,updated_at) VALUES(?,?,?,?,?,?) ON CONFLICT(job_id) DO UPDATE SET worker_id=excluded.worker_id,lease_token=excluded.lease_token,lease_expires_at=excluded.lease_expires_at,updated_at=excluded.updated_at",(row['id'],worker_id,token,expiry,now,now))
            updated=self.conn.execute("UPDATE backtest_jobs SET updated_at=? WHERE id=?",(now,row['id']))
            if updated.rowcount!=1: return None
            self.event(row['id'],'claimed',row['status'],{'worker_id':worker_id})
            claimed=self.conn.execute('SELECT j.*,l.worker_id lease_owner,l.lease_token,l.lease_expires_at FROM backtest_jobs j JOIN backtest_job_leases l ON l.job_id=j.id WHERE j.id=?',(row['id'],)).fetchone()
        return dict(claimed)
    def renew_lease(self,job_id,worker_id,token,*,lease_seconds=120):
        if not 10<=lease_seconds<=3600: raise ValueError('lease duration 10..3600s required')
        now=stamp(); expiry=datetime.fromtimestamp(datetime.now(timezone.utc).timestamp()+lease_seconds,timezone.utc).isoformat()
        with self.conn:
            res=self.conn.execute('UPDATE backtest_job_leases SET lease_expires_at=?,updated_at=? WHERE job_id=? AND worker_id=? AND lease_token=? AND lease_expires_at>?',(expiry,now,job_id,worker_id,token,now))
        return res.rowcount==1
    def release_lease(self,job_id,worker_id,token):
        now=stamp()
        with self.conn:
            res=self.conn.execute('DELETE FROM backtest_job_leases WHERE job_id=? AND worker_id=? AND lease_token=?',(job_id,worker_id,token))
        return res.rowcount==1
    def schedule_retry(self,job_id,worker_id,token,attempt,*,base_seconds=1,cap_seconds=300,rng=random.random):
        """Shared durable exponential retry schedule with full jitter; requires current lease."""
        if attempt<1 or base_seconds<1 or cap_seconds<base_seconds: raise ValueError('invalid retry bounds')
        now=datetime.now(timezone.utc); delay=min(cap_seconds,base_seconds*2**min(attempt-1,16)); delay=max(1,int(delay*(0.5+rng())))
        next_at=datetime.fromtimestamp(now.timestamp()+delay,timezone.utc).isoformat()
        with self.conn:
            lease=self.conn.execute('SELECT 1 FROM backtest_job_leases WHERE job_id=? AND worker_id=? AND lease_token=? AND lease_expires_at>?',(job_id,worker_id,token,now.isoformat())).fetchone()
            if not lease: raise RuntimeError('retry scheduling requires an active lease')
            self.conn.execute("UPDATE backtest_jobs SET status='retrying',attempt=?,retry_delay_seconds=?,next_attempt_at=?,updated_at=? WHERE id=?",(attempt,delay,next_at,now.isoformat(),job_id))
            self.conn.execute('DELETE FROM backtest_job_leases WHERE job_id=? AND lease_token=?',(job_id,token))
            self.event(job_id,'retry_scheduled','retrying',{'attempt':attempt,'delay_seconds':delay,'next_attempt_at':next_at})
        return next_at
    def transition(self,job_id,state,**data):
        row=self.conn.execute('SELECT status FROM backtest_jobs WHERE id=?',(job_id,)).fetchone()
        if not row: raise KeyError(job_id)
        old=row['status']
        if state not in TRANSITIONS.get(old,set()): raise ValueError(f'illegal job transition {old} -> {state}')
        if state=='submitted': data.setdefault('submitted_at',stamp())
        if state=='running': data.setdefault('started_at',stamp())
        if state=='completed': data.setdefault('finished_at',stamp())
        allowed={k:v for k,v in data.items() if k in {'external_job_id','external_report_id','error_class','error_message','attempt','submitted_at','started_at','finished_at'}}
        set_clause=', '.join(["status=?","updated_at=?"]+[f'{k}=?' for k in allowed])
        with self.conn:
            updated=self.conn.execute(f'UPDATE backtest_jobs SET {set_clause} WHERE id=? AND status=?',[state,stamp(),*allowed.values(),job_id,old])
            if updated.rowcount!=1: raise RuntimeError(f'concurrent job transition rejected for {job_id} from {old}')
            self.event(job_id,state,state,{k:v for k,v in allowed.items() if k not in {'error_message'}})
    def event(self,job_id,event_type,status,payload):
        self.conn.execute('INSERT INTO job_events VALUES(?,?,?,?,?,?)',(str(uuid.uuid4()),job_id,event_type,status,json.dumps(payload),stamp()))
    def recoverable(self, campaign_id=None):
        terminal=('completed','dead_letter')
        marks=','.join('?' for _ in terminal)
        if campaign_id:
            rows=self.conn.execute(f"SELECT * FROM backtest_jobs WHERE campaign_id=? AND status NOT IN ({marks}) ORDER BY created_at",(campaign_id,*terminal)).fetchall()
        else:
            rows=self.conn.execute(f"SELECT * FROM backtest_jobs WHERE status NOT IN ({marks}) ORDER BY created_at",terminal).fetchall()
        return [dict(r) for r in rows]
    def heartbeat(self,worker_id,status,capabilities=None):
        """Persist the real local worker's observed liveness; never synthesize provider auth."""
        self.conn.execute('INSERT INTO worker_heartbeats(worker_id,status,capabilities_json,seen_at) VALUES(?,?,?,?) ON CONFLICT(worker_id) DO UPDATE SET status=excluded.status,capabilities_json=excluded.capabilities_json,seen_at=excluded.seen_at',(worker_id,status,json.dumps(capabilities or {},sort_keys=True),stamp()))
        self.conn.commit()
    def finish_after_report_validation(self,job_id,report_id,validated):
        if not validated: raise ValueError('cannot complete job without a validated retrieved report')
        self.transition(job_id,'completed',external_report_id=report_id)

def error_class(exc):
    text=str(exc).lower(); kind=type(exc).__name__.lower()
    if 'rate' in text or '429' in text or 'ratelimit' in kind: return 'rate_limit'
    if isinstance(exc,TimeoutError) or 'timeout' in kind: return 'timeout'
    if isinstance(exc,PermissionError) or 'auth' in text or 'permission' in text: return 'authorization'
    if 'adapterunavailable' in kind or 'unavailable' in text: return 'provider_unavailable'
    if 'compile' in text or 'pine' in text: return 'source_validation'
    if isinstance(exc,(ValueError,TypeError)): return 'invalid_request_or_report'
    return 'provider_or_transport'

def require_start_gate(state:GateState):
    result=check(state)
    if not result['allowed']: raise PermissionError(', '.join(result['missing']))
    return result
