"""Bounded async execution worker contract; real runs require the official adapter and gate."""
import asyncio, json, logging, uuid
from dataclasses import dataclass
logger=logging.getLogger('quantlab.worker')

@dataclass(frozen=True)
class VerifiedProviderLimits:
    """Deployment-supplied limits copied from verified provider/account documentation."""
    max_concurrency: int
    requests_per_second: float
    evidence_reference: str
    verified: bool = False

    def validate(self):
        if not self.verified or not self.evidence_reference.strip():
            raise ValueError('provider limits must be verified against authoritative provider evidence before worker startup')
        if self.max_concurrency<1 or self.requests_per_second<=0:
            raise ValueError('provider concurrency and rate limits must be positive')
from .execution_gate import GateState
from .jobs import JobLedger, error_class, require_start_gate, stamp
from .metrics import ClosedTrade
from .report_store import persist_actual_report

class CampaignWorker:
    def __init__(self,ledger:JobLedger,adapter,*,max_concurrency:int,provider_limits:VerifiedProviderLimits,timeout_seconds:int=900,max_retries:int=3,backoff_base:float=1.0):
        provider_limits.validate()
        if max_concurrency<1 or max_concurrency>provider_limits.max_concurrency: raise ValueError('configured concurrency exceeds verified provider limit')
        self.ledger=ledger;self.adapter=adapter;self.semaphore=asyncio.Semaphore(max_concurrency);self.timeout=timeout_seconds;self.max_retries=max_retries;self.backoff=backoff_base;self.interval=1/provider_limits.requests_per_second;self._rate_lock=asyncio.Lock();self._last_request=0.0;self._stopping=False;self._active=set();self.worker_id=f'quantlab-{uuid.uuid4()}'
    async def _maintain_lease(self,job_id,token,parent):
        try:
            while True:
                await asyncio.sleep(30)
                if not self.ledger.renew_lease(job_id,self.worker_id,token,lease_seconds=120):
                    parent.cancel()
                    return
        except asyncio.CancelledError:
            return
    async def _rate_limit(self):
        async with self._rate_lock:
            wait=self.interval-(asyncio.get_running_loop().time()-self._last_request)
            if wait>0: await asyncio.sleep(wait)
            self._last_request=asyncio.get_running_loop().time()
    async def run(self,job:dict,*,gate:GateState):
        require_start_gate(gate) # explicit Start flag is part of the immutable preflight state
        if self._stopping: raise RuntimeError('worker is shutting down')
        lease=self.ledger.claim(self.worker_id,job_id=job['id'])
        if lease is None: return {'status':'not_claimed','reason':'job is leased, not due, or terminal'}
        task=asyncio.current_task();self._active.add(task)
        self.ledger.heartbeat(self.worker_id,'busy',{'active_jobs':len(self._active),'provider_adapter':type(self.adapter).__name__})
        lease_task=asyncio.create_task(self._maintain_lease(job['id'],lease['lease_token'],task))
        try: return await self._run_locked(lease,lease)
        finally:
            lease_task.cancel()
            await lease_task
            self.ledger.release_lease(job['id'],self.worker_id,lease['lease_token'])
            self._active.discard(task)
            if not self._stopping: self.ledger.heartbeat(self.worker_id,'busy' if self._active else 'idle',{'active_jobs':len(self._active),'provider_adapter':type(self.adapter).__name__})
    async def _run_locked(self,job,lease):
        async with self.semaphore:
            current=self.ledger.conn.execute('select status,attempt from backtest_jobs where id=?',(job['id'],)).fetchone()
            if current['status']=='completed': return {'status':'completed','report_id':job.get('external_report_id')}
            if current['status']=='dead_letter': return {'status':'dead_letter','error_class':job.get('error_class')}
            limit=min(self.max_retries+1,int(job.get('max_attempts') or self.max_retries+1))
            if current['status']=='failed' and current['attempt']>=limit:
                self.ledger.transition(job['id'],'dead_letter',error_class='retry_exhausted')
                return {'status':'dead_letter','error_class':'retry_exhausted'}
            if current['status']=='failed': self.ledger.transition(job['id'],'retrying',attempt=current['attempt']+1)
            start_attempt=max(1,current['attempt']+1)
            for attempt in range(start_attempt,limit+1):
                try:
                    return await asyncio.wait_for(self._once(job,attempt),timeout=min(self.timeout,int(job.get('timeout_seconds') or self.timeout)))
                except asyncio.CancelledError: raise
                except Exception as exc:
                    cls=error_class(exc)
                    logger.warning('backtest_job_attempt_failed',extra={'job_id':job['id'],'attempt':attempt,'error_class':cls})
                    self.ledger.transition(job['id'],'failed',error_class=cls,error_message=str(exc)[:500],attempt=attempt)
                    if attempt>=limit:
                        self.ledger.transition(job['id'],'dead_letter',error_class=cls)
                        return {'status':'dead_letter','error_class':cls}
                    self.ledger.transition(job['id'],'retrying',attempt=attempt)
                    base=max(1,int(self.backoff))
                    cap=120 if cls=='rate_limit' else 300
                    next_at=self.ledger.schedule_retry(job['id'],self.worker_id,lease['lease_token'],attempt,base_seconds=base,cap_seconds=cap)
                    return {'status':'retry_scheduled','error_class':cls,'next_attempt_at':next_at}
    async def _once(self,job,attempt):
        row=self.ledger.conn.execute('select status,external_job_id,external_report_id from backtest_jobs where id=?',(job['id'],)).fetchone()
        state=row['status'];ext_id=row['external_job_id']
        if state=='generated' or (state=='retrying' and not ext_id):
            self.ledger.transition(job['id'],'compilation_started');state='compilation_started'
        if state=='compilation_started':
            await self._rate_limit()
            if not await self.adapter.compile(job['source_snapshot']): raise ValueError('Pine source validation failed')
            self.ledger.transition(job['id'],'compiled');state='compiled'
        if state=='retrying' and ext_id:
            # A persisted provider ID is authoritative. Never submit that accepted run again.
            self.ledger.transition(job['id'],'submitted',external_job_id=ext_id,attempt=attempt);state='submitted'
        if state=='submitted' and ext_id:
            self.ledger.transition(job['id'],'accepted',external_job_id=ext_id);state='accepted'
        elif state in ('compiled','submitted'):
            if state=='compiled': self.ledger.transition(job['id'],'submitted',attempt=attempt)
            await self._rate_limit()
            # Reuse the stable idempotency key after uncertain submit acknowledgement.
            parameters=job['parameters_snapshot']
            if isinstance(parameters,str): parameters=json.loads(parameters)
            accepted=await self.adapter.submit(source=job['source_snapshot'],parameters=parameters,market=job['market'],timeframe=job['timeframe'],idempotency_key=job['idempotency_key'])
            ext_id=accepted['job_id'];self.ledger.transition(job['id'],'accepted',external_job_id=ext_id);state='accepted'
        if not ext_id: raise RuntimeError('persisted external job reference is missing; refusing to invent one')
        if state=='accepted': self.ledger.transition(job['id'],'running');state='running'
        if state=='running':
            provider_state=await self.adapter.wait(ext_id)
            if provider_state!='completed': raise RuntimeError(f'provider job ended as {provider_state}')
            self.ledger.transition(job['id'],'report_retrieval_started');state='report_retrieval_started'
        if state in ('report_retrieval_started','report_retrieved'):
            report=await self.adapter.report(ext_id)
            if not report or not await self.adapter.validate_report(report,job): raise ValueError('actual report missing or failed provenance validation')
            if not report.get('report_id'): raise ValueError('validated report is missing provider report ID')
            if state=='report_retrieval_started': self.ledger.transition(job['id'],'report_retrieved',external_report_id=report['report_id'])
            raw_parameters=job.get('parameters_snapshot') or '{}'
            parameters=json.loads(raw_parameters) if isinstance(raw_parameters,str) else raw_parameters
            trades=[]
            for item in report.get('trades') or []:
                if not isinstance(item,dict) or 'pnl' not in item or item.get('side') not in ('long','short'):
                    raise ValueError('trade evidence is missing normalized PnL or side; refusing to persist guessed rows')
                trades.append(ClosedTrade(pnl=float(item['pnl']),fees=float(item.get('fees') or 0),funding=float(item.get('funding') or 0),slippage=float(item.get('slippage') or 0),side=item['side'],entry_time=item.get('entry_time'),exit_time=item.get('exit_time'),notional=item.get('notional'),risk_amount=item.get('risk_amount')))
            report_start=report.get('interval_start') or job.get('interval_start')
            report_end=report.get('interval_end') or job.get('interval_end')
            assumptions=report.get('cost_assumptions') or report.get('assumptions')
            missing=list(report.get('unavailable_fields') or [])
            for key,value in [('interval_start',report_start),('interval_end',report_end),('provider_metrics',report.get('provider_metrics',report.get('metrics'))),('cost_assumptions',assumptions),('initial_capital',report.get('initial_capital'))]:
                if value is None: missing.append(key)
            persist_actual_report(self.ledger.conn,strategy_id=job['strategy_id'],strategy_version_id=job.get('strategy_version_id'),job_id=job['id'],adapter=type(self.adapter).__name__,external_job_id=ext_id,external_report_id=report['report_id'],source_hash=job.get('source_hash') or report.get('source_hash') or '',market=job['market'],timeframe=job['timeframe'],interval_start=report_start,interval_end=report_end,parameters=parameters,execution_started_at=job.get('started_at'),execution_completed_at=stamp(),cost_assumptions=assumptions,provider_metrics=report.get('provider_metrics',report.get('metrics')),unavailable_fields=missing,initial_capital=report.get('initial_capital'),trades=trades)
            self.ledger.finish_after_report_validation(job['id'],report['report_id'],True)
            return {'status':'completed','report_id':report['report_id']}
        raise RuntimeError(f'unsupported recovered job state {state}')
    async def recover_interrupted(self,*,gate:GateState):
        """Resume persisted non-terminal jobs after rechecking every execution precondition.

        Existing external IDs are polled, never resubmitted. An uncertain submit without an
        external ID reuses its original idempotency key through the adapter contract.
        """
        require_start_gate(gate)
        jobs=self.ledger.recoverable()
        # Every execution path claims the exact logical job before provider calls.
        return await asyncio.gather(*(self.run(job,gate=gate) for job in jobs))
    async def serve(self,gate_provider,*,poll_interval:float=2.0):
        """Persistent supervised poll loop. gate_provider must recheck current explicit consent."""
        if poll_interval<=0: raise ValueError('poll_interval must be positive')
        self._stopping=False
        self.ledger.heartbeat(self.worker_id,'starting',{'provider_adapter':type(self.adapter).__name__})
        while not self._stopping:
            try:
                gate=gate_provider() if callable(gate_provider) else gate_provider
                if asyncio.iscoroutine(gate): gate=await gate
                require_start_gate(gate)
                recovered=await self.recover_interrupted(gate=gate)
                self.ledger.heartbeat(self.worker_id,'idle',{'active_jobs':0,'recovered_jobs':len(recovered),'provider_adapter':type(self.adapter).__name__})
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.exception('worker_poll_failed',extra={'worker_id':self.worker_id,'error_class':error_class(exc)})
                self.ledger.heartbeat(self.worker_id,'degraded',{'error_class':error_class(exc),'provider_adapter':type(self.adapter).__name__})
            await asyncio.sleep(poll_interval)
    async def shutdown(self):
        self._stopping=True
        active=[task for task in self._active if task is not asyncio.current_task()]
        if active: await asyncio.gather(*active,return_exceptions=True)
        self.ledger.heartbeat(self.worker_id,'stopped',{'provider_adapter':type(self.adapter).__name__})
