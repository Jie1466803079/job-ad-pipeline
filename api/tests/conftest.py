import os

import psycopg
import pytest

from jobpipe import db

TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL",
                                   "postgresql://jobpipe:jobpipe@127.0.0.1:5433/jobpipe_test")
TABLES = ["ingest_calls", "llm_calls", "extractions", "postings", "companies"]


@pytest.fixture(scope="session")
def migrated_db() -> str:
    try:
        connection = db.connect(TEST_DATABASE_URL)
    except psycopg.OperationalError as exc:
        if os.environ.get("REQUIRE_DB"):
            raise
        pytest.skip(f"Postgres is not reachable ({exc}). Start it with `make db`.")
    with connection:
        connection.execute("DROP SCHEMA IF EXISTS public CASCADE; CREATE SCHEMA public;")
        db.migrate(connection)
    return TEST_DATABASE_URL


@pytest.fixture
def conn(migrated_db):
    with db.connect(migrated_db) as connection:
        connection.execute(f"TRUNCATE {', '.join(TABLES)} RESTART IDENTITY CASCADE")
        connection.commit()
        yield connection
