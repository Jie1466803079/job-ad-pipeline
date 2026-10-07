"""All SQL for the service. Every function takes an open connection. Callers decide when to commit."""

from dataclasses import asdict
from datetime import date, datetime, timedelta

from psycopg import Connection
from psycopg.types.json import Jsonb

from jobpipe.checks import CheckResult
from jobpipe.configfiles import CompanyConfig
from jobpipe.fit import FitResult
from jobpipe.llm.base import LLMUsage
from jobpipe.llm.schema import ExtractionPayload
from jobpipe.models import Posting
from jobpipe.routing import RouteDecision


def sync_companies(conn: Connection, companies: list[CompanyConfig]) -> None:
    """Make the companies table match config/companies.yaml. Companies missing from it are deactivated."""
    for company in companies:
        conn.execute(
            """INSERT INTO companies (name, source, slug, active) VALUES (%s, %s, %s, %s)
               ON CONFLICT (source, slug) DO UPDATE SET name = EXCLUDED.name, active = EXCLUDED.active""",
            (company.name, company.source, company.slug, company.active),
        )
    keys = [f"{company.source}/{company.slug}" for company in companies]
    conn.execute("UPDATE companies SET active = FALSE WHERE NOT (source || '/' || slug = ANY(%s))", (keys,))


def active_companies(conn: Connection) -> list[dict]:
    return conn.execute("SELECT id, name, source, slug FROM companies WHERE active ORDER BY name").fetchall()


def get_company(conn: Connection, company_id: int) -> dict | None:
    return conn.execute("SELECT id, name, source, slug, active FROM companies WHERE id = %s",
                        (company_id,)).fetchone()


def ensure_company(conn: Connection, source: str, slug: str, name: str) -> dict:
    """The company behind a submitted link, added as inactive (not polled) when it is new."""
    conn.execute("""INSERT INTO companies (name, source, slug, active) VALUES (%s, %s, %s, FALSE)
                    ON CONFLICT (source, slug) DO NOTHING""", (name, source, slug))
    return conn.execute("SELECT id, name, source, slug, active FROM companies WHERE source = %s AND slug = %s",
                        (source, slug)).fetchone()


def find_posting(conn: Connection, source: str, source_id: str) -> dict | None:
    return conn.execute("""SELECT id, status, text_hash, text_deleted_at, closed_at FROM postings
                           WHERE source = %s AND source_id = %s""", (source, source_id)).fetchone()


def insert_posting(conn: Connection, company_id: int, posting: Posting, status: str) -> int:
    row = conn.execute(
        """INSERT INTO postings (company_id, source, source_id, title, url, posted_at, board, text, text_hash, status)
           VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING id""",
        (company_id, posting.source, posting.source_id, posting.title, posting.url, posting.posted_at,
         Jsonb(posting.board.model_dump(mode="json")), posting.text, posting.text_hash, status),
    ).fetchone()
    return row["id"]


def update_posting_content(conn: Connection, posting_id: int, posting: Posting) -> None:
    """Store a changed ad, reopen it if it was closed, and restore text that had been deleted."""
    conn.execute(
        """UPDATE postings SET title = %s, url = %s, posted_at = %s, board = %s, text = %s, text_hash = %s,
                  closed_at = NULL, text_deleted_at = NULL, last_seen_at = now()
           WHERE id = %s""",
        (posting.title, posting.url, posting.posted_at, Jsonb(posting.board.model_dump(mode="json")),
         posting.text, posting.text_hash, posting_id),
    )


def touch_posting(conn: Connection, posting_id: int) -> None:
    """Seen again unchanged: refresh last_seen_at and reopen it unless its closing date has passed."""
    conn.execute(
        """UPDATE postings SET last_seen_at = now(),
                  closed_at = CASE WHEN closing_date IS NULL OR closing_date >= current_date THEN NULL
                                   ELSE closed_at END
           WHERE id = %s""",
        (posting_id,),
    )


def set_status(conn: Connection, posting_id: int, status: str, skip_reason: str | None,
               closing_date: date | None) -> None:
    conn.execute("UPDATE postings SET status = %s, skip_reason = %s, closing_date = %s WHERE id = %s",
                 (status, skip_reason, closing_date, posting_id))


def insert_extraction(conn: Connection, posting_id: int, text_hash: str, provider: str, model: str,
                      payload: ExtractionPayload | None, checks: list[CheckResult], decision: RouteDecision,
                      fit: FitResult | None) -> int:
    row = conn.execute(
        """INSERT INTO extractions (posting_id, text_hash, provider, model, fields, checks, route, reasons, fit)
           VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING id""",
        (posting_id, text_hash, provider, model,
         Jsonb(payload.model_dump()) if payload else None,
         Jsonb([check.model_dump() for check in checks]),
         decision.route,
         Jsonb(decision.reasons),
         Jsonb(fit.model_dump()) if fit else None),
    ).fetchone()
    return row["id"]


def latest_extraction(conn: Connection, posting_id: int) -> dict | None:
    return conn.execute("""SELECT * FROM extractions WHERE posting_id = %s
                           ORDER BY created_at DESC, id DESC LIMIT 1""", (posting_id,)).fetchone()


_FIT_RATIO = "jsonb_array_length(e.fit -> 'matched')::float / NULLIF((e.fit ->> 'total')::int, 0)"
_BEST_FIRST = f"{_FIT_RATIO} DESC NULLS LAST, p.closing_date ASC NULLS LAST, p.id DESC"

# Each queue tab: which ads it lists and in what order. Applications stay under applied after they close.
QUEUE_TABS: dict[str, tuple[str, str]] = {
    "review": ("p.status = 'review' AND p.closed_at IS NULL", _BEST_FIRST),
    "tracked": ("p.status = 'tracked' AND p.closed_at IS NULL", _BEST_FIRST),
    "ineligible": ("p.status = 'ineligible' AND p.closed_at IS NULL", _BEST_FIRST),
    "applied": ("p.status IN ('applied', 'interview', 'offer', 'rejected')",
                "p.decided_at DESC NULLS LAST, p.id DESC"),
    "closed": ("p.closed_at IS NOT NULL AND p.status NOT IN ('skipped', 'dismissed')",
               "p.closed_at DESC, p.id DESC"),
    "skipped": ("p.status = 'skipped'", "p.first_seen_at DESC, p.id DESC"),
    "dismissed": ("p.status = 'dismissed'", "p.decided_at DESC NULLS LAST, p.id DESC"),
}


def list_postings(conn: Connection, tab: str, limit: int) -> tuple[list[dict], int]:
    """A queue tab: its ads with their current extraction and the corrections to it, and how many there are."""
    where, order = QUEUE_TABS[tab]
    rows = conn.execute(
        f"""SELECT p.id, c.name AS company, p.title, p.url, p.status, p.skip_reason, p.closing_date,
                   p.closed_at, p.board, e.fields, e.fit, e.reasons,
                   coalesce((SELECT jsonb_agg(r.edited_fields ORDER BY r.created_at, r.id) FROM reviews r
                             WHERE r.extraction_id = e.id AND r.action = 'edit'), '[]'::jsonb) AS edits
            FROM postings p
            JOIN companies c ON c.id = p.company_id
            LEFT JOIN LATERAL (SELECT id, fields, fit, reasons FROM extractions
                               WHERE posting_id = p.id AND text_hash = p.text_hash
                               ORDER BY created_at DESC, id DESC LIMIT 1) e ON TRUE
            WHERE {where}
            ORDER BY {order}
            LIMIT %s""",
        (limit,),
    ).fetchall()
    total = conn.execute(f"SELECT count(*) AS n FROM postings p WHERE {where}").fetchone()["n"]
    return rows, total


def get_posting(conn: Connection, posting_id: int) -> dict | None:
    return conn.execute("""SELECT p.*, c.name AS company FROM postings p
                           JOIN companies c ON c.id = p.company_id WHERE p.id = %s""", (posting_id,)).fetchone()


def current_extraction(conn: Connection, posting_id: int) -> dict | None:
    """The newest extraction made from the ad's current text, or None (skipped, or only older text)."""
    return conn.execute("""SELECT e.* FROM extractions e JOIN postings p ON p.id = e.posting_id
                           WHERE e.posting_id = %s AND e.text_hash = p.text_hash
                           ORDER BY e.created_at DESC, e.id DESC LIMIT 1""", (posting_id,)).fetchone()


def extraction_history(conn: Connection, posting_id: int) -> list[dict]:
    return conn.execute("""SELECT id, model, route, fields IS NULL AS failed, created_at FROM extractions
                           WHERE posting_id = %s ORDER BY created_at, id""", (posting_id,)).fetchall()


def reviews_for(conn: Connection, posting_id: int) -> list[dict]:
    return conn.execute("""SELECT id, extraction_id, username, action, edited_fields, from_status, to_status,
                                  created_at
                           FROM reviews WHERE posting_id = %s ORDER BY created_at, id""",
                        (posting_id,)).fetchall()


def insert_llm_call(conn: Connection, posting_id: int, provider: str, model: str, usage: LLMUsage | None,
                    cost_usd: float | None, outcome: str, error: str | None) -> None:
    conn.execute(
        """INSERT INTO llm_calls (posting_id, provider, model, input_tokens, output_tokens, cost_usd,
                                  latency_ms, request_id, outcome, error)
           VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
        (posting_id, provider, model,
         usage.input_tokens if usage else None, usage.output_tokens if usage else None, cost_usd,
         usage.latency_ms if usage else None, usage.request_id if usage else None, outcome, error),
    )


def insert_ingest_call(conn: Connection, company_id: int, counts) -> None:
    data = asdict(counts)
    columns = ", ".join(data)
    placeholders = ", ".join(["%s"] * len(data))
    conn.execute(f"INSERT INTO ingest_calls (company_id, {columns}) VALUES (%s, {placeholders})",
                 (company_id, *data.values()))


def close_missing(conn: Connection, company_id: int, seen_source_ids: list[str]) -> int:
    """Close this company's open ads that were not in a complete board fetch."""
    cursor = conn.execute("""UPDATE postings SET closed_at = now()
                             WHERE company_id = %s AND closed_at IS NULL AND NOT (source_id = ANY(%s))""",
                          (company_id, seen_source_ids))
    return cursor.rowcount


def close_past_deadline(conn: Connection, today: date) -> int:
    cursor = conn.execute("UPDATE postings SET closed_at = now() WHERE closed_at IS NULL AND closing_date < %s",
                          (today,))
    return cursor.rowcount


def delete_old_text(conn: Connection, older_than: timedelta = timedelta(days=30)) -> int:
    cursor = conn.execute("""UPDATE postings SET text = NULL, text_deleted_at = now()
                             WHERE text IS NOT NULL AND closed_at IS NOT NULL AND closed_at < now() - %s""",
                          (older_than,))
    return cursor.rowcount


def digest(conn: Connection, since: datetime, today: date) -> dict:
    tracked = conn.execute(
        """SELECT p.id, c.name AS company, p.title, p.url, p.closing_date, e.fit
           FROM postings p
           JOIN companies c ON c.id = p.company_id
           JOIN LATERAL (SELECT route, fit, created_at FROM extractions
                         WHERE posting_id = p.id ORDER BY created_at DESC, id DESC LIMIT 1) e ON TRUE
           WHERE p.status = 'tracked' AND p.closed_at IS NULL AND e.route = 'tracked' AND e.created_at >= %s
           ORDER BY c.name, p.title""",
        (since,),
    ).fetchall()
    closing_soon = conn.execute(
        """SELECT p.id, c.name AS company, p.title, p.url, p.closing_date, p.status
           FROM postings p JOIN companies c ON c.id = p.company_id
           WHERE p.closed_at IS NULL AND p.status IN ('tracked', 'applied')
             AND p.closing_date BETWEEN %s AND %s
           ORDER BY p.closing_date, c.name""",
        (today, today + timedelta(days=7)),
    ).fetchall()
    review_count = conn.execute(
        "SELECT count(*) AS n FROM postings WHERE status = 'review' AND closed_at IS NULL").fetchone()["n"]
    counts = conn.execute(
        """SELECT coalesce(sum(fetched), 0) AS fetched, coalesce(sum(created), 0) AS created,
                  coalesce(sum(skipped), 0) AS skipped, coalesce(sum(tracked), 0) AS tracked,
                  coalesce(sum(review), 0) AS review, coalesce(sum(ineligible), 0) AS ineligible,
                  coalesce(sum(closed), 0) AS closed, coalesce(sum(failed), 0) AS failed
           FROM ingest_calls WHERE started_at >= %s""",
        (since,),
    ).fetchone()
    cost = conn.execute("SELECT coalesce(sum(cost_usd), 0) AS usd FROM llm_calls WHERE created_at >= %s",
                        (since,)).fetchone()["usd"]
    return {"tracked": tracked, "closing_soon": closing_soon, "review_count": review_count,
            "counts": counts, "llm_cost_usd": float(cost)}


def get_user(conn: Connection, username: str) -> dict | None:
    return conn.execute("""SELECT id, username, password_hash, failed_logins, locked_until FROM users
                           WHERE username = %s""", (username,)).fetchone()


def save_user(conn: Connection, username: str, password_hash: str) -> bool:
    """Create the user, or set a new password and clear any lockout. Returns True when the user is new."""
    existing = get_user(conn, username)
    if existing:
        conn.execute("UPDATE users SET password_hash = %s, failed_logins = 0, locked_until = NULL WHERE id = %s",
                     (password_hash, existing["id"]))
        return False
    conn.execute("INSERT INTO users (username, password_hash) VALUES (%s, %s)", (username, password_hash))
    return True


def record_failed_login(conn: Connection, user_id: int, max_failed: int, lock_until: datetime) -> datetime | None:
    """Count a failed login. The attempt that reaches max_failed locks the account and restarts the count.

    Returns locked_until, which can be an old lock that has already ended.
    """
    row = conn.execute(
        """UPDATE users
           SET failed_logins = CASE WHEN failed_logins + 1 >= %(max)s THEN 0 ELSE failed_logins + 1 END,
               locked_until = CASE WHEN failed_logins + 1 >= %(max)s THEN %(until)s ELSE locked_until END
           WHERE id = %(id)s
           RETURNING locked_until""",
        {"max": max_failed, "until": lock_until, "id": user_id},
    ).fetchone()
    return row["locked_until"]


def clear_failed_logins(conn: Connection, user_id: int) -> None:
    conn.execute("UPDATE users SET failed_logins = 0, locked_until = NULL WHERE id = %s", (user_id,))
