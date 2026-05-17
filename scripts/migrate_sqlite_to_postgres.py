from __future__ import annotations

import argparse
import json
import os
import shutil
import sqlite3
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

import psycopg
from psycopg.types.json import Jsonb


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SQLITE_DB = ROOT / "backend" / "data" / "app.db"
BACKUP_DIR = ROOT / "backups"

MIGRATION_TABLES = [
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

RESET_ORDER = [
    "application_target_windows",
    "application_people",
    "application_uploads",
    "application_targets",
    "transfer_trip_points",
    "applications",
    "transfer_trips",
    "tbgn_projects",
    "users",
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

SEQUENCE_TABLES = [
    "application_targets",
    "application_target_windows",
    "application_people",
    "application_uploads",
    "transfer_trip_points",
]


def repo_path(path: Path) -> str:
    try:
        return str(path.relative_to(ROOT)).replace("\\", "/")
    except ValueError:
        return str(path)


def connect_sqlite(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    return conn


def connect_postgres() -> psycopg.Connection[Any]:
    database_url = os.environ.get("DATABASE_URL", "").strip()
    if not database_url:
        raise RuntimeError("DATABASE_URL is not set")
    return psycopg.connect(database_url)


def sqlite_columns(conn: sqlite3.Connection, table: str) -> list[str]:
    return [row["name"] for row in conn.execute(f"PRAGMA table_info({table})")]


def postgres_columns(conn: psycopg.Connection[Any], table: str) -> list[str]:
    rows = conn.execute(
        """
        SELECT column_name
        FROM information_schema.columns
        WHERE table_schema = 'public' AND table_name = %s
        ORDER BY ordinal_position
        """,
        (table,),
    ).fetchall()
    return [row[0] for row in rows]


def sqlite_count(conn: sqlite3.Connection, table: str) -> int:
    return int(conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])


def postgres_count(conn: psycopg.Connection[Any], table: str) -> int:
    return int(conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])


def load_sqlite_rows(conn: sqlite3.Connection, table: str) -> list[dict[str, Any]]:
    return [dict(row) for row in conn.execute(f"SELECT * FROM {table}")]


def postgres_segment_ids(conn: psycopg.Connection[Any]) -> set[str]:
    return {row[0] for row in conn.execute("SELECT segment_id FROM tram_segments")}


def classify_missing_segments(
    rows_by_table: dict[str, list[dict[str, Any]]],
    valid_segment_ids: set[str],
) -> dict[str, list[str]]:
    missing: dict[str, list[str]] = {
        "application_targets": [],
        "transfer_trip_points": [],
    }
    for table in missing:
        for row in rows_by_table.get(table, []):
            segment_id = row.get("segment_id")
            if segment_id and segment_id not in valid_segment_ids:
                missing[table].append(str(segment_id))
    return missing


def print_counts(
    sqlite_conn: sqlite3.Connection,
    pg_conn: psycopg.Connection[Any],
    title: str,
) -> None:
    print(title)
    for table in MIGRATION_TABLES:
        print(
            f"{table}: sqlite={sqlite_count(sqlite_conn, table)} "
            f"postgres={postgres_count(pg_conn, table)}"
        )


def create_backup(sqlite_path: Path) -> Path:
    if not sqlite_path.exists():
        raise RuntimeError(f"SQLite database not found: {repo_path(sqlite_path)}")
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = BACKUP_DIR / f"app_{timestamp}_before_postgres_migration.db"
    if backup_path.exists():
        raise RuntimeError(f"Backup already exists: {repo_path(backup_path)}")
    shutil.copy2(sqlite_path, backup_path)
    return backup_path


def parse_route_geometry(value: Any) -> Any:
    if value is None or value == "":
        return None
    if isinstance(value, (dict, list)):
        return Jsonb(value)
    return Jsonb(json.loads(str(value)))


def normalize_row(table: str, row: dict[str, Any], valid_segment_ids: set[str]) -> dict[str, Any]:
    normalized = dict(row)
    if table == "users":
        normalized["is_admin"] = bool(normalized.get("is_admin"))
    if table == "transfer_trips":
        normalized["route_geometry"] = parse_route_geometry(normalized.get("route_geometry"))
    if table in {"application_targets", "transfer_trip_points"}:
        segment_id = normalized.get("segment_id")
        if segment_id and segment_id not in valid_segment_ids:
            normalized["segment_id"] = None
    return normalized


def upsert_row(conn: psycopg.Connection[Any], table: str, row: dict[str, Any], columns: list[str]) -> None:
    pk = PRIMARY_KEYS[table]
    placeholders = ", ".join(["%s"] * len(columns))
    quoted_columns = ", ".join(columns)
    update_columns = [column for column in columns if column != pk]
    if update_columns:
        update_sql = ", ".join(f"{column} = EXCLUDED.{column}" for column in update_columns)
        conflict_sql = f"DO UPDATE SET {update_sql}"
    else:
        conflict_sql = "DO NOTHING"
    sql = (
        f"INSERT INTO {table} ({quoted_columns}) VALUES ({placeholders}) "
        f"ON CONFLICT ({pk}) {conflict_sql}"
    )
    conn.execute(sql, [row.get(column) for column in columns])


def reset_relational_tables(conn: psycopg.Connection[Any]) -> None:
    wior_refs = conn.execute(
        "SELECT COUNT(*) FROM wior_work_areas WHERE application_id IS NOT NULL"
    ).fetchone()[0]
    if wior_refs:
        raise RuntimeError(
            "Refusing --reset-relational because wior_work_areas has application references; "
            "resetting applications would modify spatial WIOR rows."
        )
    for table in RESET_ORDER:
        conn.execute(f"DELETE FROM {table}")


def reset_sequences(conn: psycopg.Connection[Any]) -> None:
    for table in SEQUENCE_TABLES:
        column = PRIMARY_KEYS[table]
        conn.execute(
            f"""
            SELECT setval(
                pg_get_serial_sequence('{table}', '{column}'),
                COALESCE((SELECT MAX({column}) FROM {table}), 1),
                (SELECT COALESCE(MAX({column}), 0) > 0 FROM {table})
            )
            """
        )


def migrate_rows(
    sqlite_conn: sqlite3.Connection,
    pg_conn: psycopg.Connection[Any],
    valid_segment_ids: set[str],
) -> dict[str, int]:
    migrated: dict[str, int] = {}
    pg_columns_by_table = {table: postgres_columns(pg_conn, table) for table in MIGRATION_TABLES}
    sqlite_columns_by_table = {table: sqlite_columns(sqlite_conn, table) for table in MIGRATION_TABLES}

    for table in MIGRATION_TABLES:
        common_columns = [
            column
            for column in sqlite_columns_by_table[table]
            if column in pg_columns_by_table[table]
        ]
        if not common_columns:
            raise RuntimeError(f"No common columns found for {table}")
        rows = load_sqlite_rows(sqlite_conn, table)
        for row in rows:
            normalized = normalize_row(table, row, valid_segment_ids)
            upsert_row(pg_conn, table, normalized, common_columns)
        migrated[table] = len(rows)
    reset_sequences(pg_conn)
    return migrated


def print_missing_segment_warnings(missing_segments: dict[str, list[str]]) -> None:
    for table, values in missing_segments.items():
        unique_values = sorted(set(values))
        if not unique_values:
            print(f"{table}: all non-null source segment_id values exist in tram_segments")
            continue
        sample = ", ".join(unique_values[:8])
        print(
            f"warning: {table} has {len(values)} source rows with segment_id values missing "
            f"from tram_segments; these will be migrated with segment_id=NULL. "
            f"sample: {sample}"
        )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Dry-run or apply relational SQLite to PostgreSQL migration."
    )
    parser.add_argument(
        "--sqlite-db",
        type=Path,
        default=DEFAULT_SQLITE_DB,
        help="Path to source SQLite app.db",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Actually write relational rows to PostgreSQL. Default is dry-run.",
    )
    parser.add_argument(
        "--reset-relational",
        action="store_true",
        help="Delete existing PostgreSQL relational rows before applying. Never touches spatial tables.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    sqlite_path = args.sqlite_db.resolve()
    if not sqlite_path.exists():
        print(f"error: SQLite database not found: {repo_path(sqlite_path)}", file=sys.stderr)
        return 1

    try:
        with connect_sqlite(sqlite_path) as sqlite_conn, connect_postgres() as pg_conn:
            rows_by_table = {
                table: load_sqlite_rows(sqlite_conn, table)
                for table in MIGRATION_TABLES
            }
            valid_segment_ids = postgres_segment_ids(pg_conn)
            missing_segments = classify_missing_segments(rows_by_table, valid_segment_ids)

            print(f"Source SQLite: {repo_path(sqlite_path)}")
            print(f"Mode: {'apply' if args.apply else 'dry-run'}")
            print_counts(sqlite_conn, pg_conn, "\nCounts before migration:")
            print()
            print_missing_segment_warnings(missing_segments)

            if not args.apply:
                print("\nDry-run only. No PostgreSQL rows were inserted, updated, or deleted.")
                return 0

            backup_path = create_backup(sqlite_path)
            print(f"\nCreated SQLite backup: {repo_path(backup_path)}")

            with pg_conn.transaction():
                if args.reset_relational:
                    print("Resetting PostgreSQL relational tables before migration.")
                    reset_relational_tables(pg_conn)
                migrated = migrate_rows(sqlite_conn, pg_conn, valid_segment_ids)

            print("\nMigrated rows:")
            for table in MIGRATION_TABLES:
                print(f"{table}: {migrated[table]}")
            print_counts(sqlite_conn, pg_conn, "\nCounts after migration:")
            print("\nMigration applied. The application runtime still uses SQLite.")
            return 0
    except Exception as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
