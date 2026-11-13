"""Backtesting adapter contracts. The TradingKit MCP implementation is intentionally absent.

The packaged TradingKit integration is host-managed MCP, not a documented REST API. Never
replace this unavailable adapter with guessed endpoints or successful fake report payloads.
"""
from dataclasses import dataclass
from typing import Protocol, Any

@dataclass
class AdapterCapabilities:
    connected: bool
    authenticated: bool
    available: bool
    reason: str
    tools: tuple[str, ...] = ()
    max_concurrency: int | None = None

class BacktestAdapter(Protocol):
    async def capabilities(self) -> AdapterCapabilities: ...
    async def submit(self, *, source: str, market: str, timeframe: str, idempotency_key: str) -> Any: ...
    async def status(self, *, external_job_id: str) -> Any: ...
    async def report(self, *, external_report_id: str) -> Any: ...

class TradingKitAdapterUnavailable:
    async def capabilities(self) -> AdapterCapabilities:
        return AdapterCapabilities(False, False, False, "No authenticated host-managed TradingKit MCP bridge is configured.")
    async def submit(self, **kwargs):
        raise RuntimeError("TradingKit MCP unavailable; no backtest was submitted.")
    async def status(self, **kwargs):
        raise RuntimeError("TradingKit MCP unavailable; job status cannot be read.")
    async def report(self, **kwargs):
        raise RuntimeError("TradingKit MCP unavailable; report cannot be retrieved.")
