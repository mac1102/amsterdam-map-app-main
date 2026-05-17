from __future__ import annotations

import os
import sqlite3
import sys
from datetime import date, datetime
from pathlib import Path
from typing import Any

import psycopg
from psycopg.rows import dict_row


ROOT = Path(__file__).resolve().parents[1]
SQLITE_DB = ROOT / "backend" / "data" / "app.db"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


COUNT_TABLES = [
    "applications",
    "application_targets",
    "application_uploads",
]


def database_url() -> str:
    return os.getenv("DATABASE_URL", "").strip()


def sqlite_scalar(conn: sqlite3.Connection, sql: str) -> Any:
    return conn.execute(sql).fetchone()[0]


def normalize_datetime(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.replace(tzinfo=None)
    if isinstance(value, date):
        return datetime(value.year, value.month, value.day)
    raw = str(value).strip()
    if not raw:
        return None
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed.replace(tzinfo=None) if parsed.tzinfo is not None else parsed


def postgres_scalar(conn: psycopg.Connection[dict[str, Any]], sql: str) -> Any:
    row = conn.execute(sql).fetchone()
    if row is None:
        return None
    return next(iter(row.values()))


def print_warning(message: str) -> None:
    print(f"WARNING: {message}")


def main() -> int:
    url = database_url()
    if not url:
        print("error: DATABASE_URL is not set", file=sys.stderr)
        return 1

    warnings = 0
    with sqlite3.connect(SQLITE_DB) as sqlite_conn, psycopg.connect(url, row_factory=dict_row) as pg_conn:
        for table in COUNT_TABLES:
            sqlite_count = int(sqlite_scalar(sqlite_conn, f"SELECT COUNT(*) FROM {table}"))
            pg_count = int(postgres_scalar(pg_conn, f"SELECT COUNT(*) FROM {table}"))
            match = sqlite_count == pg_count
            print(
                f"{table}: sqlite_count={sqlite_count} "
                f"postgres_count={pg_count} match={match}"
            )
            if sqlite_count > pg_count:
                warnings += 1
                print_warning(
                    "PostgreSQL read mirror is stale. "
                    "Run migrate_sqlite_to_postgres.py --apply --reset-relational before testing APP_DB_BACKEND=postgres."
                )
            elif pg_count > sqlite_count:
                warnings += 1
                print_warning(
                    f"PostgreSQL has {pg_count - sqlite_count} more {table} rows than SQLite; "
                    "verify the mirror was reset from the current SQLite snapshot."
                )

        sqlite_latest = normalize_datetime(
            sqlite_scalar(sqlite_conn, "SELECT MAX(submitted_at) FROM applications")
        )
        pg_latest = normalize_datetime(
            postgres_scalar(pg_conn, "SELECT MAX(submitted_at) FROM applications")
        )
        print(
            "applications_latest_submitted_at: "
            f"sqlite={sqlite_latest.isoformat() if sqlite_latest else None} "
            f"postgres={pg_latest.isoformat() if pg_latest else None}"
        )
        if sqlite_latest and (pg_latest is None or sqlite_latest > pg_latest):
            warnings += 1
            print_warning(
                "PostgreSQL read mirror is stale. "
                "Run migrate_sqlite_to_postgres.py --apply --reset-relational before testing APP_DB_BACKEND=postgres."
            )

    print(f"warnings: {warnings}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
