"""Bounded async execution worker contract; real runs require the official adapter and gate."""
import asyncio, logging
logger=logging.getLogger('quantlab.worker')
from .execution_gate import GateState
from .jobs import JobLedger, error_class, require_start_gate

class CampaignWorker:
    def __init__(self,ledger:JobLedger,adapter,*,max_concurrency:int,timeout_seconds:int=900,max_retries:int=3,backoff_base:float=1.0,requests_per_second:float=1.0):
        if max_concurrency<1 or requests_per_second<=0: raise ValueError('positive bounded concurrency and request rate required')
        self.ledger=ledger;self.adapter=adapter;self.semaphore=asyncio.Semaphore(max_concurrency);self.timeout=timeout_seconds;self.max_retries=max_retries;self.backoff=backoff_base;self.interval=1/requests_per_second;self._rate_lock=asyncio.Lock();self._last_request=0.0;self._stopping=False;self._active=set()
    async def _rate_limit(self):
        async with self._rate_lock:
            wait=self.interval-(asyncio.get_running_loop().time()-self._last_request)
            if wait>0: await asyncio.sleep(wait)
            self._last_request=asyncio.get_running_loop().time()
    async def run(self,job:dict,*,gate:GateState):
        require_start_gate(gate) # explicit Start flag is part of the immutable preflight state
        if self._stopping: raise RuntimeError('worker is shutting down')
        task=asyncio.current_task();self._active.add(task)
        try: return await self._run_locked(job)
        finally: self._active.discard(task)
    async def _run_locked(self,job):
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
                    delay=min(self.backoff*(2**(attempt-1)),60)
                    if cls=='rate_limit': delay=min(max(delay,5),120)
                    await asyncio.sleep(delay)
    async def _once(self,job,attempt):
        row=self.ledger.conn.execute('select status,external_job_id,external_report_id from backtest_jobs where id=?',(job['id'],)).fetchone()
        state=row['status'];ext_id=row['external_job_id']
        if state in ('generated','retrying'):
            self.ledger.transition(job['id'],'compilation_started');state='compilation_started'
        if state=='compilation_started':
            await self._rate_limit()
            if not await self.adapter.compile(job['source_snapshot']): raise ValueError('Pine source validation failed')
            self.ledger.transition(job['id'],'compiled');state='compiled'
        if state in ('compiled','submitted'):
            if state=='compiled': self.ledger.transition(job['id'],'submitted',attempt=attempt)
            await self._rate_limit()
            # Always reuse the original key after an uncertain submit acknowledgement.
            accepted=await self.adapter.submit(source=job['source_snapshot'],parameters=job['parameters_snapshot'],market=job['market'],timeframe=job['timeframe'],idempotency_key=job['idempotency_key'])
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
            if state=='report_retrieval_started': self.ledger.transition(job['id'],'report_retrieved',external_report_id=report['report_id'])
            self.ledger.finish_after_report_validation(job['id'],report['report_id'],True)
            return {'status':'completed','report_id':report['report_id']}
        raise RuntimeError(f'unsupported recovered job state {state}')
    async def recover_interrupted(self,*,gate:GateState):
        """Resume persisted non-terminal jobs after rechecking every execution precondition.

        Existing external IDs are polled, never resubmitted. An uncertain submit without an
        external ID reuses its original idempotency key through the adapter contract.
        """
        require_start_gate(gate)
        results=[]
        for job in self.ledger.recoverable():
            results.append(await self.run(job,gate=gate))
        return results
    async def shutdown(self):
        self._stopping=True
        active=[task for task in self._active if task is not asyncio.current_task()]
        if active: await asyncio.gather(*active,return_exceptions=True)
