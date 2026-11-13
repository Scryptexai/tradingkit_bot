from pathlib import Path
from datetime import datetime, timezone

def apply(conn):
    conn.execute('CREATE TABLE IF NOT EXISTS schema_migrations(version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL)')
    if not conn.execute('SELECT 1 FROM schema_migrations WHERE version=1').fetchone():
        sql=Path(__file__).with_name('001_research_core.sql').read_text()
        conn.executescript(sql)
        conn.execute('INSERT OR IGNORE INTO schema_migrations VALUES(1,?)',(datetime.now(timezone.utc).isoformat(),))
        conn.commit()
