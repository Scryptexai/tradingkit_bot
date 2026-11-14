import sqlite3
import pytest
from app.metrics import ClosedTrade, evaluate
from app.report_store import persist_actual_report

def test_metrics_after_costs_and_drawdown_scope():
    got=evaluate([ClosedTrade(120,fees=2),ClosedTrade(-40,fees=1,side='short'),ClosedTrade(30)],initial_capital=1000)
    assert got['trade_count']==3
    assert got['net_profit']==107
    assert got['win_rate']==pytest.approx(2/3)
    assert got['gross_profit']==150 and got['gross_loss']==40
    assert got['profit_factor']==pytest.approx(148/41)
    assert got['max_drawdown_close_to_close']==pytest.approx(41/1_118) # equity 1000 -> 1118 -> 1077

def test_exposure_uses_union_of_overlapping_trade_intervals_and_normalizes_naive_times():
    trades=[ClosedTrade(1,entry_time='2025-01-01T00:00:00',exit_time='2025-01-01T00:10:00'),ClosedTrade(1,entry_time='2025-01-01T00:05:00+00:00',exit_time='2025-01-01T00:15:00+00:00'),ClosedTrade(1,entry_time='2025-01-01T00:20:00Z',exit_time='2025-01-01T00:30:00Z')]
    assert evaluate(trades)['exposure_time_ratio']==pytest.approx(25/30)

def test_metrics_reject_nonfinite_trade_values():
    with pytest.raises(ValueError): evaluate([ClosedTrade(float('nan'))])

def test_report_persistence_is_idempotent_by_external_ref():
    conn=sqlite3.connect(':memory:')
    args=dict(strategy_id='s1',strategy_version_id='v3',job_id='internal-job',adapter='TradingKit',external_job_id='job',external_report_id='report',source_hash='hash',market='BTCUSDT',timeframe='1h',interval_start='2025-01-01T00:00:00Z',interval_end='2025-02-01T00:00:00Z',parameters={'period':20},execution_started_at='2025-02-01T00:01:00Z',execution_completed_at='2025-02-01T00:02:00Z',cost_assumptions={'fees':0.1,'slippage':2,'funding_applicable':True},provider_metrics={'netProfit':10},trades=[ClosedTrade(10)])
    rid=persist_actual_report(conn,**args)
    assert conn.execute('select count(*) from report_trades where report_id=?',(rid,)).fetchone()[0]==1
    report=conn.execute('select job_id,strategy_version_id,source_hash,interval_start,interval_end,parameters_json,provider_metrics_json,actual_trade_count,unavailable_fields_json from reports where id=?',(rid,)).fetchone()
    assert report[:8]==('internal-job','v3','hash',args['interval_start'],args['interval_end'],'{"period":20}','{"netProfit":10}',1)
    assert 'initial_capital' in report[8]
    assert persist_actual_report(conn,**args)==rid
    with pytest.raises(ValueError,match='different provenance'):
        persist_actual_report(conn,**{**args,'source_hash':'changed'})
