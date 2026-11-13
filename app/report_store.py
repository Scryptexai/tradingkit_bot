"""Durable normalized report persistence; invoked only after a real adapter fetch validates data."""
import json, sqlite3, uuid
from datetime import datetime, timezone
from typing import Iterable
from .metrics import ClosedTrade, evaluate

def init_report_tables(conn: sqlite3.Connection) -> None:
    conn.execute('''CREATE TABLE IF NOT EXISTS reports(
        id TEXT PRIMARY KEY, strategy_id TEXT NOT NULL, adapter TEXT NOT NULL,
        external_job_id TEXT NOT NULL, external_report_id TEXT NOT NULL,
        source_hash TEXT NOT NULL, market TEXT NOT NULL, timeframe TEXT NOT NULL,
        returned_at TEXT NOT NULL, metrics TEXT NOT NULL,
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

def persist_actual_report(conn: sqlite3.Connection, *, strategy_id: str, adapter: str,
                          external_job_id: str, external_report_id: str, source_hash: str,
                          market: str, timeframe: str, trades: Iterable[ClosedTrade],
                          initial_capital: float=1.0) -> str:
    """Persist received report + complete trades transactionally. Caller must supply fetched source pins."""
    if not all((strategy_id,adapter,external_job_id,external_report_id,source_hash,market,timeframe)):
        raise ValueError("report provenance identifiers are required")
    trade_list=list(trades)
    metrics=evaluate(trade_list,initial_capital=initial_capital)
    rid=str(uuid.uuid4()); stamp=datetime.now(timezone.utc).isoformat()
    with conn:
        init_report_tables(conn)
        conn.execute("INSERT INTO reports VALUES(?,?,?,?,?,?,?,?,?,?)",(rid,strategy_id,adapter,external_job_id,external_report_id,source_hash,market,timeframe,stamp,json.dumps(metrics)))
        conn.executemany("INSERT INTO report_trades(report_id,trade_index,pnl,fees,funding,side,slippage,entry_time,exit_time,notional,risk_amount) VALUES(?,?,?,?,?,?,?,?,?,?,?)",[(rid,i,t.pnl,t.fees,t.funding,t.side,t.slippage,t.entry_time,t.exit_time,t.notional,t.risk_amount) for i,t in enumerate(trade_list)])
    return rid
