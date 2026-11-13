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

def test_report_persistence_is_idempotent_by_external_ref():
    conn=sqlite3.connect(':memory:')
    args=dict(strategy_id='s1',adapter='TradingKit',external_job_id='job',external_report_id='report',source_hash='hash',market='BTCUSDT',timeframe='1h',trades=[ClosedTrade(10)])
    rid=persist_actual_report(conn,**args)
    assert conn.execute('select count(*) from report_trades where report_id=?',(rid,)).fetchone()[0]==1
    with pytest.raises(sqlite3.IntegrityError): persist_actual_report(conn,**args)
