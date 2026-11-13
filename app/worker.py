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
            for attempt in range(1,self.max_retries+2):
                try:
                    return await asyncio.wait_for(self._once(job,attempt),timeout=min(self.timeout,int(job.get('timeout_seconds') or self.timeout)))
                except asyncio.CancelledError: raise
                except Exception as exc:
                    cls=error_class(exc)
                    logger.warning('backtest_job_attempt_failed',extra={'job_id':job['id'],'attempt':attempt,'error_class':cls})
                    self.ledger.transition(job['id'],'failed',error_class=cls,error_message=str(exc)[:500],attempt=attempt)
                    if attempt>self.max_retries:
                        self.ledger.transition(job['id'],'dead_letter',error_class=cls)
                        return {'status':'dead_letter','error_class':cls}
                    self.ledger.transition(job['id'],'retrying',attempt=attempt)
                    delay=min(self.backoff*(2**(attempt-1)),60)
                    if cls=='rate_limit': delay=min(max(delay,5),120)
                    await asyncio.sleep(delay)
    async def _once(self,job,attempt):
        current=self.ledger.conn.execute('select status from backtest_jobs where id=?',(job['id'],)).fetchone()['status']
        if current=='generated': self.ledger.transition(job['id'],'compilation_started')
        elif current=='retrying': self.ledger.transition(job['id'],'compilation_started')
        await self._rate_limit()
        compiled=await self.adapter.compile(job['source_snapshot'])
        if not compiled: raise ValueError('Pine source validation failed')
        self.ledger.transition(job['id'],'compiled')
        self.ledger.transition(job['id'],'submitted',attempt=attempt)
        await self._rate_limit()
        accepted=await self.adapter.submit(source=job['source_snapshot'],parameters=job['parameters_snapshot'],market=job['market'],timeframe=job['timeframe'],idempotency_key=job['idempotency_key'])
        ext_id=accepted['job_id'];self.ledger.transition(job['id'],'accepted',external_job_id=ext_id)
        self.ledger.transition(job['id'],'running')
        state=await self.adapter.wait(ext_id)
        if state!='completed': raise RuntimeError(f'provider job ended as {state}')
        self.ledger.transition(job['id'],'report_retrieval_started')
        report=await self.adapter.report(ext_id)
        if not report or not await self.adapter.validate_report(report,job): raise ValueError('actual report missing or failed provenance validation')
        self.ledger.transition(job['id'],'report_retrieved',external_report_id=report['report_id'])
        self.ledger.finish_after_report_validation(job['id'],report['report_id'],True)
        return {'status':'completed','report_id':report['report_id']}
    async def shutdown(self):
        self._stopping=True
        active=[task for task in self._active if task is not asyncio.current_task()]
        if active: await asyncio.gather(*active,return_exceptions=True)
