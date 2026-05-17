from __future__ import annotations

import os
import sqlite3
import subprocess
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


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def database_url() -> str:
    return os.getenv("DATABASE_URL", "").strip()


def postgres_conn() -> psycopg.Connection[dict[str, Any]]:
    url = database_url()
    if not url:
        raise RuntimeError("DATABASE_URL is not set")
    return psycopg.connect(url, row_factory=dict_row)


def scalar(conn: psycopg.Connection[dict[str, Any]], sql: str, params: tuple[Any, ...] = ()) -> Any:
    row = conn.execute(sql, params).fetchone()
    return next(iter(row.values())) if row else None


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


def print_step(title: str) -> None:
    print(f"\n== {title} ==")


def check_postgis_reachable_and_schema() -> None:
    print_step("PostGIS reachability and schema")
    required_tables = [
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
    required_views = [
        "user_activity_view",
        "admin_activity_view",
        "system_activity_view",
    ]
    with postgres_conn() as conn:
        db = scalar(conn, "SELECT current_database()")
        user = scalar(conn, "SELECT current_user")
        postgis_version = scalar(conn, "SELECT postgis_full_version()")
        require(bool(postgis_version), "PostGIS extension is not reachable")
        print(f"connected database={db} user={user}")

        for name in required_tables + required_views:
            exists = scalar(conn, "SELECT to_regclass(%s) IS NOT NULL", (f"public.{name}",))
            require(bool(exists), f"Missing PostgreSQL object: {name}")
        print(f"schema objects present: {len(required_tables)} tables, {len(required_views)} views")


def check_static_gis_and_wior_counts() -> None:
    print_step("Static GIS and WIOR mirror counts")
    with postgres_conn() as conn:
        counts = {
            "tram_lines": int(scalar(conn, "SELECT COUNT(*) FROM tram_lines") or 0),
            "tram_segments": int(scalar(conn, "SELECT COUNT(*) FROM tram_segments") or 0),
            "tram_stops": int(scalar(conn, "SELECT COUNT(*) FROM tram_stops") or 0),
            "wior_work_areas": int(
                scalar(
                    conn,
                    "SELECT COUNT(*) FROM wior_work_areas WHERE source = 'wior_sqlite_serving'",
                )
                or 0
            ),
        }
    for name, count in counts.items():
        print(f"{name}: {count}")
        require(count > 0, f"{name} has no rows")


def check_relational_mirror_current() -> None:
    print_step("Relational mirror freshness")
    require(SQLITE_DB.exists(), f"SQLite app database is missing: {SQLITE_DB}")
    tables = ["applications", "application_targets", "application_uploads"]
    with sqlite3.connect(SQLITE_DB) as sqlite_conn, postgres_conn() as pg_conn:
        for table in tables:
            sqlite_count = int(sqlite_scalar(sqlite_conn, f"SELECT COUNT(*) FROM {table}"))
            pg_count = int(scalar(pg_conn, f"SELECT COUNT(*) FROM {table}") or 0)
            print(f"{table}: sqlite={sqlite_count} postgres={pg_count}")
            require(sqlite_count == pg_count, f"{table} count mismatch; rerun migration before verification")

        sqlite_latest = normalize_datetime(sqlite_scalar(sqlite_conn, "SELECT MAX(submitted_at) FROM applications"))
        pg_latest = normalize_datetime(scalar(pg_conn, "SELECT MAX(submitted_at) FROM applications"))
        print(
            "applications latest submitted_at: "
            f"sqlite={sqlite_latest.isoformat() if sqlite_latest else None} "
            f"postgres={pg_latest.isoformat() if pg_latest else None}"
        )
        if sqlite_latest:
            require(pg_latest is not None and pg_latest >= sqlite_latest, "PostgreSQL applications mirror is stale")


def check_health(mode: str) -> None:
    print_step(f"FastAPI health in {mode} mode")
    os.environ["APP_DB_BACKEND"] = mode
    import backend.main as app_main

    health = app_main.health_check()
    print(health)
    require(health.get("status") == "ok", f"health_check status is not ok in {mode} mode")
    resolved = (health.get("app_db_backend") or {}).get("resolved")
    require(resolved == mode, f"health_check resolved backend {resolved!r}, expected {mode!r}")


def run_command(label: str, args: list[str], require_output_contains: str | None = None) -> None:
    print_step(label)
    env = os.environ.copy()
    env["APP_DB_BACKEND"] = "postgres"
    completed = subprocess.run(
        args,
        cwd=ROOT,
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    print(completed.stdout, end="" if completed.stdout.endswith("\n") else "\n")
    require(completed.returncode == 0, f"{label} failed with exit code {completed.returncode}")
    if require_output_contains:
        require(
            require_output_contains in completed.stdout,
            f"{label} output did not include {require_output_contains!r}",
        )


def run_existing_verification_scripts() -> None:
    py = sys.executable
    checks = [
        ("check_postgis_data", [py, "scripts/check_postgis_data.py"]),
        ("check_relational_migration", [py, "scripts/check_relational_migration.py"]),
        (
            "check_postgres_read_staleness",
            [py, "scripts/check_postgres_read_staleness.py"],
            "warnings: 0",
        ),
        ("compare_sqlite_postgres_reads", [py, "scripts/compare_sqlite_postgres_reads.py"]),
        ("test_read_route_backend_modes", [py, "scripts/test_read_route_backend_modes.py"]),
        ("test_read_routes_http_modes", [py, "scripts/test_read_routes_http_modes.py"]),
        ("wior_refresh_and_sync_job", [py, "-m", "backend.wior_refresh_and_sync_job"]),
        ("test_wior_conflict_modes", [py, "scripts/test_wior_conflict_modes.py"]),
        ("test_wior_refresh_and_sync_job", [py, "scripts/test_wior_refresh_and_sync_job.py"]),
        ("test_audit_logs", [py, "scripts/test_audit_logs.py"]),
        ("test_postgres_write_mode", [py, "scripts/test_postgres_write_mode.py"]),
        ("test_api_click_modes", [py, "scripts/test_api_click_modes.py"]),
    ]
    for item in checks:
        label = item[0]
        args = item[1]
        required = item[2] if len(item) > 2 else None
        run_command(label, args, required)


def main() -> int:
    os.environ["APP_DB_BACKEND"] = "postgres"
    check_postgis_reachable_and_schema()
    check_static_gis_and_wior_counts()
    check_relational_mirror_current()
    check_health("postgres")
    run_existing_verification_scripts()
    check_health("sqlite")

    print_step("Manual browser verification")
    print("Open docs/phase11_local_verification_checklist.md and complete the browser-only checks.")
    print("Phase 11 local verification passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
