from pathlib import Path
import re
from datetime import datetime, timezone


def _stamp():
    return datetime.now(timezone.utc).isoformat()


def _apply_provenance(conn):
    """Apply migration 002 idempotently across crashes during SQLite column adds."""
    sql=Path(__file__).with_name('002_execution_provenance.sql').read_text()
    for statement in (part.strip() for part in sql.split(';') if part.strip()):
        match=re.match(r'ALTER TABLE (\w+) ADD COLUMN (\w+) (.+)',statement,re.I)
        if match:
            table,column,_ddl=match.groups()
            columns={row[1] for row in conn.execute(f'PRAGMA table_info({table})')}
            if column not in columns: conn.execute(statement)
        else:
            conn.execute(statement)


def apply(conn):
    conn.execute('CREATE TABLE IF NOT EXISTS schema_migrations(version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL)')
    if not conn.execute('SELECT 1 FROM schema_migrations WHERE version=1').fetchone():
        sql=Path(__file__).with_name('001_research_core.sql').read_text()
        conn.executescript(sql)
        conn.execute('INSERT OR IGNORE INTO schema_migrations VALUES(1,?)',(_stamp(),))
        conn.commit()
    if not conn.execute('SELECT 1 FROM schema_migrations WHERE version=2').fetchone():
        with conn:
            _apply_provenance(conn)
            conn.execute('INSERT OR IGNORE INTO schema_migrations VALUES(2,?)',(_stamp(),))
    if not conn.execute('SELECT 1 FROM schema_migrations WHERE version=3').fetchone():
        with conn:
            conn.execute('CREATE TABLE IF NOT EXISTS backtest_job_leases(job_id TEXT PRIMARY KEY REFERENCES backtest_jobs(id),worker_id TEXT NOT NULL,lease_token TEXT NOT NULL UNIQUE,lease_expires_at TEXT NOT NULL,claimed_at TEXT NOT NULL,updated_at TEXT NOT NULL)')
            conn.execute('INSERT OR IGNORE INTO schema_migrations VALUES(3,?)',(_stamp(),))
