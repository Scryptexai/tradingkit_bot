"""Durable idempotent job ledger and strict execution state machine."""
import json, sqlite3, uuid
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
    def create(self,*,campaign_id,strategy_id,strategy_version_id,idempotency_key,source,parameters,market,timeframe,max_attempts=3,timeout_seconds=900):
        if not idempotency_key or len(idempotency_key)>128: raise ValueError('idempotency key required (max 128 chars)')
        jid=str(uuid.uuid4()); ts=stamp()
        # Serialize idempotency lookup + insert so concurrent dispatchers cannot create
        # duplicate logical jobs. The unique DB constraint remains the final guard.
        try:
            with self.conn:
                existing=self.conn.execute('SELECT * FROM backtest_jobs WHERE idempotency_key=?',(idempotency_key,)).fetchone()
                if existing: return dict(existing),False
                self.conn.execute('INSERT INTO backtest_jobs(id,campaign_id,strategy_id,strategy_version_id,status,idempotency_key,source_snapshot,parameters_snapshot,market,timeframe,max_attempts,timeout_seconds,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)',(jid,campaign_id,strategy_id,strategy_version_id,'generated',idempotency_key,source,json.dumps(parameters,sort_keys=True),market,timeframe,max_attempts,timeout_seconds,ts,ts))
                self.event(jid,'strategy_generated','generated',{})
        except sqlite3.IntegrityError:
            existing=self.conn.execute('SELECT * FROM backtest_jobs WHERE idempotency_key=?',(idempotency_key,)).fetchone()
            if existing: return dict(existing),False
            raise
        return dict(self.conn.execute('SELECT * FROM backtest_jobs WHERE id=?',(jid,)).fetchone()),True
    def transition(self,job_id,state,**data):
        row=self.conn.execute('SELECT status FROM backtest_jobs WHERE id=?',(job_id,)).fetchone()
        if not row: raise KeyError(job_id)
        old=row['status']
        if state not in TRANSITIONS.get(old,set()): raise ValueError(f'illegal job transition {old} -> {state}')
        allowed={k:v for k,v in data.items() if k in {'external_job_id','external_report_id','error_class','error_message','attempt'}}
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
    def finish_after_report_validation(self,job_id,report_id,validated):
        if not validated: raise ValueError('cannot complete job without a validated retrieved report')
        self.transition(job_id,'completed',external_report_id=report_id)

def error_class(exc):
    text=str(exc).lower()
    if 'rate' in text or '429' in text: return 'rate_limit'
    if isinstance(exc,TimeoutError): return 'timeout'
    if 'auth' in text or 'permission' in text: return 'authorization'
    if 'compile' in text or 'pine' in text: return 'source_validation'
    return 'provider_or_transport'

def require_start_gate(state:GateState):
    result=check(state)
    if not result['allowed']: raise PermissionError(', '.join(result['missing']))
    return result
