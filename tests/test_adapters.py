import asyncio
import pytest
from app.adapters import AdapterUnavailable, BacktestAdapter, TradingKitAdapterUnavailable


def test_unavailable_tradingkit_adapter_reports_real_runtime_blocker():
    async def go():
        adapter=TradingKitAdapterUnavailable()
        health=await adapter.capabilities()
        assert not health.connected and not health.authenticated and not health.available
        assert 'no TradingKit MCP host transport' in health.reason
        assert isinstance(adapter,BacktestAdapter)
        for operation in (
            adapter.compile('//@version=6'),
            adapter.submit(source='//@version=6',parameters={},market='BTCUSDT',timeframe='1h',idempotency_key='unit-test'),
            adapter.wait('provider-id'),
            adapter.report('provider-id'),
            adapter.validate_report({},{}),
        ):
            with pytest.raises(AdapterUnavailable): await operation
    asyncio.run(go())
