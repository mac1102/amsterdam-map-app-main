from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
from typing import Iterable


ROOT = Path(__file__).resolve().parents[1]
SCHEMA_PATH = ROOT / "database" / "schema_postgres.sql"

EXPECTED_TABLES = [
    "users",
    "tram_lines",
    "tram_segments",
    "tram_stops",
    "applications",
    "application_targets",
    "application_target_windows",
    "application_people",
    "application_uploads",
    "transfer_trips",
    "transfer_trip_points",
    "tbgn_projects",
    "wior_work_areas",
    "audit_logs",
]

EXPECTED_INDEXES = [
    "tram_segments_geom_idx",
    "tram_stops_geom_idx",
    "wior_work_areas_geom_idx",
    "wior_work_areas_wior_id_uidx",
    "wior_work_areas_dates_idx",
    "wior_work_areas_status_idx",
    "applications_status_idx",
    "applications_dates_idx",
    "application_targets_segment_idx",
    "application_targets_application_idx",
    "audit_logs_created_at_idx",
    "audit_logs_actor_email_created_at_idx",
    "audit_logs_action_scope_created_at_idx",
    "audit_logs_entity_idx",
    "audit_logs_action_created_at_idx",
]

RESET_TABLES = [
    "audit_logs",
    "wior_work_areas",
    "transfer_trip_points",
    "transfer_trips",
    "application_uploads",
    "application_people",
    "application_target_windows",
    "application_targets",
    "applications",
    "tbgn_projects",
    "tram_stops",
    "tram_segments",
    "tram_lines",
    "users",
]


def get_database_url() -> str:
    return os.getenv("DATABASE_URL", "").strip()


def require_psycopg():
    try:
        import psycopg
    except ImportError as exc:
        raise SystemExit(
            "psycopg is not installed. Run: py -3 -m pip install -r requirements.txt"
        ) from exc
    return psycopg


def format_missing(kind: str, missing: Iterable[str]) -> str:
    return f"Missing {kind}: " + ", ".join(sorted(missing))


def reset_schema(conn) -> None:
    from psycopg import sql

    with conn.cursor() as cur:
        for table in RESET_TABLES:
            cur.execute(
                sql.SQL("DROP TABLE IF EXISTS {} CASCADE").format(
                    sql.Identifier(table)
                )
            )


def apply_schema(conn) -> None:
    if not SCHEMA_PATH.exists():
        raise SystemExit(f"Schema file not found: {SCHEMA_PATH}")

    schema_sql = SCHEMA_PATH.read_text(encoding="utf-8")
    with conn.cursor() as cur:
        cur.execute(schema_sql)


def fetch_single(cur, query: str, params=None):
    cur.execute(query, params)
    row = cur.fetchone()
    return row[0] if row else None


def validate_schema(conn) -> None:
    missing_tables = []
    missing_indexes = []

    with conn.cursor() as cur:
        cur.execute("SELECT current_database(), current_user")
        database_name, current_user = cur.fetchone()
        print(f"Connected to database '{database_name}' as '{current_user}'")

        postgis_version = fetch_single(cur, "SELECT postgis_full_version()")
        print(f"PostGIS version: {postgis_version}")

        for table in EXPECTED_TABLES:
            exists = fetch_single(cur, "SELECT to_regclass(%s)", (f"public.{table}",))
            if exists is None:
                missing_tables.append(table)

        cur.execute(
            """
            SELECT indexname
            FROM pg_indexes
            WHERE schemaname = 'public'
            """
        )
        existing_indexes = {row[0] for row in cur.fetchall()}
        for index in EXPECTED_INDEXES:
            if index not in existing_indexes:
                missing_indexes.append(index)

    if missing_tables:
        raise SystemExit(format_missing("tables", missing_tables))
    if missing_indexes:
        raise SystemExit(format_missing("indexes", missing_indexes))

    print("Tables present: " + ", ".join(EXPECTED_TABLES))
    print("Required indexes present: " + ", ".join(EXPECTED_INDEXES))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Initialize the local PostgreSQL/PostGIS schema."
    )
    parser.add_argument(
        "--reset",
        action="store_true",
        help="Drop known migration tables before recreating them. This is destructive.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    database_url = get_database_url()
    if not database_url:
        print("DATABASE_URL is not set.", file=sys.stderr)
        return 2

    psycopg = require_psycopg()

    try:
        conn = psycopg.connect(database_url, connect_timeout=5)
    except Exception as exc:
        print(f"Failed to connect to PostgreSQL: {exc}", file=sys.stderr)
        return 1

    with conn:
        if args.reset:
            print("Reset flag passed; dropping known PostgreSQL migration tables.")
            reset_schema(conn)

        apply_schema(conn)
        validate_schema(conn)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
