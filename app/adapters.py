"""Backtest adapter contract consumed by CampaignWorker.

The bundled TradingKit integration is host-managed MCP. No runtime authenticated MCP
transport/tool registry is present in this checkout, so this module deliberately does not
invent OAuth, REST endpoints, tool schemas, or provider evidence.
"""
from dataclasses import dataclass
from typing import Any, Mapping, Protocol, runtime_checkable

@dataclass(frozen=True)
class AdapterCapabilities:
    connected: bool
    authenticated: bool
    available: bool
    reason: str
    tools: tuple[str, ...] = ()
    max_concurrency: int | None = None
    account_ref: str | None = None
    raw: Mapping[str, Any] | None = None

class AdapterUnavailable(RuntimeError):
    """Provider access is not configured or not authorized; no operation was attempted."""

@runtime_checkable
class BacktestAdapter(Protocol):
    """Exact asynchronous contract used by CampaignWorker; research only, never trading."""
    async def capabilities(self) -> AdapterCapabilities: ...
    async def compile(self, source: str) -> bool: ...
    async def submit(self, *, source: str, parameters: Mapping[str, Any], market: str,
                     timeframe: str, idempotency_key: str) -> Mapping[str, str]: ...
    async def wait(self, external_job_id: str) -> str: ...
    async def report(self, external_job_id: str) -> Mapping[str, Any]: ...
    async def validate_report(self, report: Mapping[str, Any], job: Mapping[str, Any]) -> bool: ...

class TradingKitAdapterUnavailable:
    """Fail-closed placeholder until a supported authenticated MCP host bridge is supplied."""
    async def capabilities(self) -> AdapterCapabilities:
        return AdapterCapabilities(False, False, False,
            "Blocked: this runtime has no TradingKit MCP host transport, OAuth session, or discovered tool schemas.")
    async def compile(self, source: str) -> bool:
        raise AdapterUnavailable("Official TradingKit compiler/codegen tool was not discovered; source was not validated.")
    async def submit(self, **kwargs):
        raise AdapterUnavailable("TradingKit MCP unavailable; no backtest was submitted.")
    async def wait(self, external_job_id: str) -> str:
        raise AdapterUnavailable("TradingKit MCP unavailable; provider job status cannot be read.")
    async def report(self, external_job_id: str):
        raise AdapterUnavailable("TradingKit MCP unavailable; provider report cannot be retrieved.")
    async def validate_report(self, report, job) -> bool:
        raise AdapterUnavailable("TradingKit MCP unavailable; report provenance cannot be verified.")
