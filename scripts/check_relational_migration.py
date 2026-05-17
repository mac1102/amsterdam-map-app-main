from __future__ import annotations

import os
import sqlite3
import sys
from pathlib import Path
from typing import Any

import psycopg


ROOT = Path(__file__).resolve().parents[1]
SQLITE_DB = ROOT / "backend" / "data" / "app.db"

TABLES = [
    "users",
    "applications",
    "application_targets",
    "application_target_windows",
    "application_people",
    "application_uploads",
    "transfer_trips",
    "transfer_trip_points",
    "tbgn_projects",
]

PRIMARY_KEYS = {
    "users": "email",
    "applications": "application_id",
    "application_targets": "id",
    "application_target_windows": "id",
    "application_people": "id",
    "application_uploads": "id",
    "transfer_trips": "transfer_trip_id",
    "transfer_trip_points": "id",
    "tbgn_projects": "id",
}


def connect_sqlite() -> sqlite3.Connection:
    conn = sqlite3.connect(SQLITE_DB)
    conn.row_factory = sqlite3.Row
    return conn


def connect_postgres() -> psycopg.Connection[Any]:
    database_url = os.environ.get("DATABASE_URL", "").strip()
    if not database_url:
        raise RuntimeError("DATABASE_URL is not set")
    return psycopg.connect(database_url)


def sqlite_scalar(conn: sqlite3.Connection, sql: str, params: tuple[Any, ...] = ()) -> Any:
    return conn.execute(sql, params).fetchone()[0]


def pg_scalar(conn: psycopg.Connection[Any], sql: str, params: tuple[Any, ...] = ()) -> Any:
    return conn.execute(sql, params).fetchone()[0]


def sqlite_values(conn: sqlite3.Connection, sql: str) -> set[Any]:
    return {row[0] for row in conn.execute(sql)}


def pg_values(conn: psycopg.Connection[Any], sql: str) -> set[Any]:
    return {row[0] for row in conn.execute(sql)}


def print_count_comparison(sqlite_conn: sqlite3.Connection, pg_conn: psycopg.Connection[Any]) -> None:
    print("Row counts:")
    for table in TABLES:
        sqlite_count = int(sqlite_scalar(sqlite_conn, f"SELECT COUNT(*) FROM {table}"))
        pg_count = int(pg_scalar(pg_conn, f"SELECT COUNT(*) FROM {table}"))
        match = sqlite_count == pg_count
        print(f"{table}: sqlite={sqlite_count} postgres={pg_count} match={match}")
        if not match:
            print(f"warning: row count mismatch for {table}")


def print_primary_key_comparison(sqlite_conn: sqlite3.Connection, pg_conn: psycopg.Connection[Any]) -> None:
    print("\nPrimary key preservation:")
    for table in TABLES:
        pk = PRIMARY_KEYS[table]
        sqlite_ids = sqlite_values(sqlite_conn, f"SELECT {pk} FROM {table}")
        pg_ids = pg_values(pg_conn, f"SELECT {pk} FROM {table}")
        missing = sorted(sqlite_ids - pg_ids)
        extra = sorted(pg_ids - sqlite_ids)
        print(
            f"{table}.{pk}: missing_in_postgres={len(missing)} "
            f"extra_in_postgres={len(extra)}"
        )
        if missing:
            print(f"warning: sample missing {table}.{pk}: {missing[:8]}")
        if extra:
            print(f"warning: sample extra {table}.{pk}: {extra[:8]}")


def print_join_check(label: str, sqlite_missing: int, pg_missing: int) -> None:
    print(f"{label}: sqlite_missing={sqlite_missing} postgres_missing={pg_missing}")
    if sqlite_missing or pg_missing:
        print(f"warning: join check has missing references for {label}")


def print_join_checks(sqlite_conn: sqlite3.Connection, pg_conn: psycopg.Connection[Any]) -> None:
    print("\nJoin checks:")
    print_join_check(
        "applications -> users",
        int(
            sqlite_scalar(
                sqlite_conn,
                """
                SELECT COUNT(*)
                FROM applications AS a
                LEFT JOIN users AS u ON u.email = a.submitted_by_email
                WHERE u.email IS NULL
                """,
            )
        ),
        int(
            pg_scalar(
                pg_conn,
                """
                SELECT COUNT(*)
                FROM applications AS a
                LEFT JOIN users AS u ON u.email = a.submitted_by_email
                WHERE u.email IS NULL
                """,
            )
        ),
    )
    print_join_check(
        "application_targets -> applications",
        int(
            sqlite_scalar(
                sqlite_conn,
                """
                SELECT COUNT(*)
                FROM application_targets AS t
                LEFT JOIN applications AS a ON a.application_id = t.application_id
                WHERE a.application_id IS NULL
                """,
            )
        ),
        int(
            pg_scalar(
                pg_conn,
                """
                SELECT COUNT(*)
                FROM application_targets AS t
                LEFT JOIN applications AS a ON a.application_id = t.application_id
                WHERE a.application_id IS NULL
                """,
            )
        ),
    )
    print_join_check(
        "application_people -> applications",
        int(
            sqlite_scalar(
                sqlite_conn,
                """
                SELECT COUNT(*)
                FROM application_people AS p
                LEFT JOIN applications AS a ON a.application_id = p.application_id
                WHERE a.application_id IS NULL
                """,
            )
        ),
        int(
            pg_scalar(
                pg_conn,
                """
                SELECT COUNT(*)
                FROM application_people AS p
                LEFT JOIN applications AS a ON a.application_id = p.application_id
                WHERE a.application_id IS NULL
                """,
            )
        ),
    )
    print_join_check(
        "application_uploads -> applications",
        int(
            sqlite_scalar(
                sqlite_conn,
                """
                SELECT COUNT(*)
                FROM application_uploads AS u
                LEFT JOIN applications AS a ON a.application_id = u.application_id
                WHERE a.application_id IS NULL
                """,
            )
        ),
        int(
            pg_scalar(
                pg_conn,
                """
                SELECT COUNT(*)
                FROM application_uploads AS u
                LEFT JOIN applications AS a ON a.application_id = u.application_id
                WHERE a.application_id IS NULL
                """,
            )
        ),
    )
    print_join_check(
        "transfer_trip_points -> transfer_trips",
        int(
            sqlite_scalar(
                sqlite_conn,
                """
                SELECT COUNT(*)
                FROM transfer_trip_points AS p
                LEFT JOIN transfer_trips AS t ON t.transfer_trip_id = p.transfer_trip_id
                WHERE t.transfer_trip_id IS NULL
                """,
            )
        ),
        int(
            pg_scalar(
                pg_conn,
                """
                SELECT COUNT(*)
                FROM transfer_trip_points AS p
                LEFT JOIN transfer_trips AS t ON t.transfer_trip_id = p.transfer_trip_id
                WHERE t.transfer_trip_id IS NULL
                """,
            )
        ),
    )


def print_password_hash_check(sqlite_conn: sqlite3.Connection, pg_conn: psycopg.Connection[Any]) -> None:
    sqlite_hashes = {
        row["email"]: row["password_hash"]
        for row in sqlite_conn.execute("SELECT email, password_hash FROM users")
    }
    pg_hashes = {
        row[0]: row[1]
        for row in pg_conn.execute("SELECT email, password_hash FROM users")
    }
    mismatches = [
        email
        for email, password_hash in sqlite_hashes.items()
        if pg_hashes.get(email) != password_hash
    ]
    print(f"\nPassword hash preservation: mismatches={len(mismatches)}")
    if mismatches:
        print(f"warning: password hash mismatch sample: {mismatches[:8]}")


def print_segment_checks(sqlite_conn: sqlite3.Connection, pg_conn: psycopg.Connection[Any]) -> None:
    valid_segment_ids = pg_values(pg_conn, "SELECT segment_id FROM tram_segments")
    sqlite_segment_ids = [
        row[0]
        for row in sqlite_conn.execute(
            "SELECT segment_id FROM application_targets WHERE segment_id IS NOT NULL"
        )
    ]
    sqlite_missing = sorted({segment_id for segment_id in sqlite_segment_ids if segment_id not in valid_segment_ids})
    sqlite_matching_count = sum(1 for segment_id in sqlite_segment_ids if segment_id in valid_segment_ids)

    pg_non_null = int(
        pg_scalar(
            pg_conn,
            "SELECT COUNT(*) FROM application_targets WHERE segment_id IS NOT NULL",
        )
    )
    pg_matching = int(
        pg_scalar(
            pg_conn,
            """
            SELECT COUNT(*)
            FROM application_targets AS target
            JOIN tram_segments AS segment ON segment.segment_id = target.segment_id
            WHERE target.segment_id IS NOT NULL
            """,
        )
    )
    pg_missing = int(
        pg_scalar(
            pg_conn,
            """
            SELECT COUNT(*)
            FROM application_targets AS target
            LEFT JOIN tram_segments AS segment ON segment.segment_id = target.segment_id
            WHERE target.segment_id IS NOT NULL AND segment.segment_id IS NULL
            """,
        )
    )

    print("\nSegment ID checks:")
    print(f"SQLite application_targets non-null segment_id count: {len(sqlite_segment_ids)}")
    print(f"SQLite source segment_id values matching tram_segments: {sqlite_matching_count}")
    print(f"SQLite source segment_id values missing from tram_segments: {len(sqlite_missing)}")
    if sqlite_missing:
        print(f"warning: SQLite missing segment_id samples: {sqlite_missing[:8]}")
    print(f"PostgreSQL application_targets non-null segment_id count: {pg_non_null}")
    print(f"PostgreSQL application_targets matching tram_segments: {pg_matching}")
    print(f"PostgreSQL application_targets missing tram_segments: {pg_missing}")
    if pg_missing:
        rows = pg_conn.execute(
            """
            SELECT target.id, target.segment_id
            FROM application_targets AS target
            LEFT JOIN tram_segments AS segment ON segment.segment_id = target.segment_id
            WHERE target.segment_id IS NOT NULL AND segment.segment_id IS NULL
            ORDER BY target.id
            LIMIT 8
            """
        ).fetchall()
        print(f"warning: PostgreSQL missing segment_id samples: {rows}")


def main() -> int:
    try:
        with connect_sqlite() as sqlite_conn, connect_postgres() as pg_conn:
            print_count_comparison(sqlite_conn, pg_conn)
            print_primary_key_comparison(sqlite_conn, pg_conn)
            print_join_checks(sqlite_conn, pg_conn)
            print_password_hash_check(sqlite_conn, pg_conn)
            print_segment_checks(sqlite_conn, pg_conn)
            return 0
    except Exception as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
