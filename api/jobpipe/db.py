"""Connections and schema migrations."""

from importlib import resources

import psycopg
from psycopg.rows import dict_row


def connect(url: str) -> psycopg.Connection:
    return psycopg.connect(url, row_factory=dict_row)


def migrate(conn: psycopg.Connection) -> list[str]:
    """Apply the SQL files in jobpipe/migrations that have not been applied yet, in name order."""
    conn.execute("CREATE TABLE IF NOT EXISTS schema_migrations "
                 "(version TEXT PRIMARY KEY, applied_at TIMESTAMPTZ NOT NULL DEFAULT now())")
    done = {row["version"] for row in conn.execute("SELECT version FROM schema_migrations").fetchall()}
    files = sorted((f for f in resources.files("jobpipe.migrations").iterdir() if f.name.endswith(".sql")),
                   key=lambda f: f.name)
    applied = []
    for file in files:
        if file.name in done:
            continue
        conn.execute(file.read_text(encoding="utf-8"))
        conn.execute("INSERT INTO schema_migrations (version) VALUES (%s)", (file.name,))
        applied.append(file.name)
    conn.commit()
    return applied
