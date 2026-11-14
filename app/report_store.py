"""Idempotent report/trade persistence with immutable execution provenance."""
import json, sqlite3, uuid
from datetime import datetime, timezone
from typing import Iterable, Mapping, Any
from .metrics import ClosedTrade, evaluate

REPORT_COLUMNS={
 'job_id':'TEXT','strategy_version_id':'TEXT','interval_start':'TEXT','interval_end':'TEXT',
 'parameters_json':'TEXT','execution_started_at':'TEXT','execution_completed_at':'TEXT',
 'cost_assumptions_json':'TEXT','provider_metrics_json':'TEXT','unavailable_fields_json':'TEXT',
 'actual_trade_count':'INTEGER'
}

def init_report_tables(conn: sqlite3.Connection) -> None:
    conn.execute('''CREATE TABLE IF NOT EXISTS reports(
        id TEXT PRIMARY KEY, strategy_id TEXT NOT NULL, adapter TEXT NOT NULL,
        external_job_id TEXT NOT NULL, external_report_id TEXT NOT NULL,
        source_hash TEXT NOT NULL, market TEXT NOT NULL, timeframe TEXT NOT NULL,
        returned_at TEXT NOT NULL, metrics TEXT NOT NULL,
        job_id TEXT, strategy_version_id TEXT, interval_start TEXT, interval_end TEXT,
        parameters_json TEXT, execution_started_at TEXT, execution_completed_at TEXT,
        cost_assumptions_json TEXT, provider_metrics_json TEXT, unavailable_fields_json TEXT,
        actual_trade_count INTEGER,
        UNIQUE(adapter, external_report_id))''')
    conn.execute('''CREATE TABLE IF NOT EXISTS report_trades(
        id INTEGER PRIMARY KEY AUTOINCREMENT, report_id TEXT NOT NULL,
        trade_index INTEGER NOT NULL, pnl REAL NOT NULL, fees REAL NOT NULL,
        funding REAL NOT NULL, side TEXT NOT NULL, slippage REAL NOT NULL DEFAULT 0,
        entry_time TEXT, exit_time TEXT, notional REAL, risk_amount REAL,
        FOREIGN KEY(report_id) REFERENCES reports(id), UNIQUE(report_id,trade_index))''')
    existing={r[1] for r in conn.execute('PRAGMA table_info(report_trades)')}
    for column, ddl in [('slippage','REAL NOT NULL DEFAULT 0'),('entry_time','TEXT'),('exit_time','TEXT'),('notional','REAL'),('risk_amount','REAL')]:
        if column not in existing: conn.execute(f'ALTER TABLE report_trades ADD COLUMN {column} {ddl}')
    existing={r[1] for r in conn.execute('PRAGMA table_info(reports)')}
    for column, ddl in REPORT_COLUMNS.items():
        if column not in existing: conn.execute(f'ALTER TABLE reports ADD COLUMN {column} {ddl}')

def persist_actual_report(conn: sqlite3.Connection, *, strategy_id: str, adapter: str,
                          external_job_id: str, external_report_id: str, source_hash: str,
                          market: str, timeframe: str, trades: Iterable[ClosedTrade],
                          job_id: str | None=None, strategy_version_id: str | None=None,
                          interval_start: str | None=None, interval_end: str | None=None,
                          parameters: Mapping[str,Any] | None=None,
                          execution_started_at: str | None=None, execution_completed_at: str | None=None,
                          cost_assumptions: Mapping[str,Any] | None=None,
                          provider_metrics: Mapping[str,Any] | None=None,
                          unavailable_fields: Iterable[str] | None=None,
                          initial_capital: float | None=None) -> str:
    """Store only supplied provider evidence; absent provenance is explicitly enumerated."""
    if not all((strategy_id,adapter,external_job_id,external_report_id,source_hash,market,timeframe)):
        raise ValueError("report provenance identifiers are required")
    if (interval_start is None)!=(interval_end is None):
        raise ValueError("historical interval bounds must both be supplied or both be unavailable")
    trade_list=list(trades)
    computed_metrics=evaluate(trade_list,initial_capital=initial_capital)
    missing=set(unavailable_fields or ())
    for key,value in {
        'internal_job_id':job_id,'strategy_version_id':strategy_version_id,
        'historical_interval':interval_start if interval_end is not None else None,
        'parameters':parameters,'execution_started_at':execution_started_at,
        'execution_completed_at':execution_completed_at,'cost_assumptions':cost_assumptions,
        'provider_metrics':provider_metrics,'initial_capital':initial_capital
    }.items():
        if value is None: missing.add(key)
    report_id=str(uuid.uuid4()); stamp=datetime.now(timezone.utc).isoformat()
    encoded=lambda v: json.dumps(v,sort_keys=True,separators=(',',':')) if v is not None else None
    with conn:
        init_report_tables(conn)
        existing=conn.execute('SELECT id,strategy_id,external_job_id,source_hash FROM reports WHERE adapter=? AND external_report_id=?',(adapter,external_report_id)).fetchone()
        if existing:
            if (existing[1],existing[2],existing[3])!=(strategy_id,external_job_id,source_hash):
                raise ValueError('provider report id already exists with different provenance; refusing overwrite')
            return existing[0]
        conn.execute('''INSERT INTO reports(
          id,strategy_id,adapter,external_job_id,external_report_id,source_hash,market,timeframe,returned_at,metrics,
          job_id,strategy_version_id,interval_start,interval_end,parameters_json,execution_started_at,execution_completed_at,
          cost_assumptions_json,provider_metrics_json,unavailable_fields_json,actual_trade_count)
          VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',
          (report_id,strategy_id,adapter,external_job_id,external_report_id,source_hash,market,timeframe,stamp,
           encoded(computed_metrics),job_id,strategy_version_id,interval_start,interval_end,encoded(parameters),
           execution_started_at,execution_completed_at,encoded(cost_assumptions),encoded(provider_metrics),
           encoded(sorted(missing)),len(trade_list)))
        conn.executemany("INSERT INTO report_trades(report_id,trade_index,pnl,fees,funding,side,slippage,entry_time,exit_time,notional,risk_amount) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
          [(report_id,i,t.pnl,t.fees,t.funding,t.side,t.slippage,t.entry_time,t.exit_time,t.notional,t.risk_amount) for i,t in enumerate(trade_list)])
    return report_id
