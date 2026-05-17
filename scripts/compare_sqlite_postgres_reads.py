from __future__ import annotations

import json
import os
import sqlite3
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

os.environ.setdefault("APP_DB_BACKEND", "sqlite")

ROOT = Path(__file__).resolve().parents[1]
SQLITE_DB = ROOT / "backend" / "data" / "app.db"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.postgres_app_queries import (  # noqa: E402
    PostgresAppQueries,
    _admin_application_row_to_summary,
    _default_asset_label,
    _default_asset_source,
    _normalize_application_target_type,
    _parse_json_value,
    _serialize_transfer_trip,
    _tbgn_row_to_dict,
)


class Comparison:
    def __init__(self) -> None:
        self.failures: list[str] = []
        self.warnings: list[str] = []

    def ok(self, label: str) -> None:
        print(f"PASS {label}")

    def fail(self, label: str, detail: str) -> None:
        message = f"FAIL {label}: {detail}"
        self.failures.append(message)
        print(message)

    def warn(self, label: str, detail: str) -> None:
        message = f"WARN {label}: {detail}"
        self.warnings.append(message)
        print(message)

    def equal(self, label: str, left: Any, right: Any) -> None:
        normalized_left = normalize_value(left)
        normalized_right = normalize_value(right)
        if normalized_left == normalized_right:
            self.ok(label)
            return
        self.fail(label, f"sqlite={normalized_left!r} postgres={normalized_right!r}")


def connect_sqlite() -> sqlite3.Connection:
    conn = sqlite3.connect(SQLITE_DB)
    conn.row_factory = sqlite3.Row
    return conn


def row_dict(row: sqlite3.Row | None) -> dict[str, Any] | None:
    if row is None:
        return None
    return dict(row)


def rows(conn: sqlite3.Connection, sql: str, params: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
    return [dict(row) for row in conn.execute(sql, params).fetchall()]


def scalar_sqlite(conn: sqlite3.Connection, sql: str, params: tuple[Any, ...] = ()) -> Any:
    return conn.execute(sql, params).fetchone()[0]


def scalar_pg(pg: PostgresAppQueries, sql: str, params: tuple[Any, ...] = ()) -> Any:
    row = pg._conn().execute(sql, params).fetchone()
    if row is None:
        return None
    return next(iter(row.values()))


def valid_tram_segment_ids(pg: PostgresAppQueries) -> set[str]:
    return {row["segment_id"] for row in pg._conn().execute("SELECT segment_id FROM tram_segments")}


def normalize_datetime_string(value: str) -> str:
    raw = value.strip()
    if "T" not in raw:
        return raw
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return value
    if parsed.tzinfo is not None:
        parsed = parsed.replace(tzinfo=None)
    return parsed.isoformat()


def normalize_value(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: normalize_value(value[key]) for key in sorted(value)}
    if isinstance(value, list):
        return [normalize_value(item) for item in value]
    if isinstance(value, tuple):
        return tuple(normalize_value(item) for item in value)
    if isinstance(value, str):
        return normalize_datetime_string(value)
    return value


def parse_tbgn_geometry_text(value: Any) -> Any:
    if value is None:
        return None
    raw = str(value or "").strip()
    if not raw:
        return None
    return json.loads(raw)


def sqlite_admin_application_summary(row: dict[str, Any]) -> dict[str, Any]:
    return _admin_application_row_to_summary(row)


def sqlite_application_targets(conn: sqlite3.Connection, application_id: str) -> list[dict[str, Any]]:
    return rows(
        conn,
        """
        SELECT id, target_index,
               coalesce(nullif(target_type, ''), 'rail_segment') AS target_type,
               coalesce(nullif(asset_id, ''), segment_id, '') AS asset_id,
               asset_label, asset_source,
               segment_id, line_id, line_name, work_mode,
               work_start_x, work_start_y, work_end_x, work_end_y,
               project_start, project_end
        FROM application_targets
        WHERE application_id = ?
        ORDER BY target_index ASC
        """,
        (application_id,),
    )


def sqlite_application_target_windows(conn: sqlite3.Connection, application_id: str) -> list[dict[str, Any]]:
    return rows(
        conn,
        """
        SELECT
            t.id AS target_id,
            w.window_index,
            w.project_start,
            w.project_end,
            w.label
        FROM application_targets t
        LEFT JOIN application_target_windows w
          ON w.target_id = t.id
        WHERE t.application_id = ?
        ORDER BY t.target_index ASC, w.window_index ASC
        """,
        (application_id,),
    )


def sqlite_application_people(conn: sqlite3.Connection, application_id: str) -> list[dict[str, Any]]:
    return rows(
        conn,
        """
        SELECT target_index, first_name, last_name, phone, email, employee_id
        FROM application_people
        WHERE application_id = ?
        ORDER BY CASE WHEN target_index IS NULL THEN -1 ELSE target_index END ASC
        """,
        (application_id,),
    )


def sqlite_application_uploads(conn: sqlite3.Connection, application_id: str) -> list[dict[str, Any]]:
    return rows(
        conn,
        """
        SELECT original_filename, stored_filename
        FROM application_uploads
        WHERE application_id = ?
        ORDER BY id ASC
        """,
        (application_id,),
    )


def sqlite_application_detail(conn: sqlite3.Connection, row: dict[str, Any]) -> dict[str, Any]:
    application_id = row["application_id"]
    targets = sqlite_application_targets(conn, application_id)
    target_windows = sqlite_application_target_windows(conn, application_id)
    people = sqlite_application_people(conn, application_id)
    uploads = sqlite_application_uploads(conn, application_id)

    windows_by_target: dict[int, list[dict[str, Any]]] = {}
    for target in targets:
        windows_by_target[target["id"]] = []

    for window in target_windows:
        target_id = window["target_id"]
        windows_by_target.setdefault(target_id, [])
        if window["window_index"] is None:
            continue
        windows_by_target[target_id].append(
            {
                "project_start": window["project_start"],
                "project_end": window["project_end"],
                "label": window["label"] or "Custom work",
            }
        )

    serialized_targets: list[dict[str, Any]] = []
    for target in targets:
        target_type = _normalize_application_target_type(target["target_type"])
        asset_id = str(target["asset_id"] or target["segment_id"] or "").strip()
        segment_id = str(target["segment_id"] or "").strip()
        asset_label = str(target["asset_label"] or "").strip() or _default_asset_label(
            target_type,
            asset_id,
            segment_id,
        )
        asset_source = str(target["asset_source"] or "").strip() or _default_asset_source(target_type)
        schedules = windows_by_target.get(target["id"], [])
        if not schedules:
            schedules = [
                {
                    "project_start": target["project_start"],
                    "project_end": target["project_end"],
                    "label": "Custom work",
                }
            ]

        serialized_targets.append(
            {
                "target_index": target["target_index"],
                "target_type": target_type,
                "asset_id": asset_id,
                "asset_label": asset_label,
                "asset_source": asset_source,
                "segment_id": target["segment_id"],
                "line_id": target["line_id"],
                "line_name": target["line_name"],
                "work_mode": target["work_mode"],
                "work_start_point": (
                    {"x": target["work_start_x"], "y": target["work_start_y"]}
                    if target["work_start_x"] is not None and target["work_start_y"] is not None
                    else None
                ),
                "work_end_point": (
                    {"x": target["work_end_x"], "y": target["work_end_y"]}
                    if target["work_end_x"] is not None and target["work_end_y"] is not None
                    else None
                ),
                "project_start": target["project_start"],
                "project_end": target["project_end"],
                "schedules": schedules,
            }
        )

    return {
        "item_type": "work_application",
        "application_id": row["application_id"],
        "submitted_at": row["submitted_at"],
        "status": row["status"],
        "submitted_by_email": row["submitted_by_email"],
        "person_mode": row["person_mode"],
        "admin_note": row["admin_note"],
        "decision_message": row["decision_message"],
        "work_details": {
            "description": row["work_description"],
            "source": row["work_source"],
            "urgency": row["urgency"],
            "affected_lines": row["affected_lines"],
            "notes": row["work_notes"],
        },
        "contact_details": {
            "coordinator": row["coordinator"],
            "vvw_measure": row["vvw_measure"],
        },
        "targets": serialized_targets,
        "people": [
            {
                "target_index": person["target_index"],
                "first_name": person["first_name"],
                "last_name": person["last_name"],
                "phone": person["phone"],
                "email": person["email"],
                "employee_id": person["employee_id"],
            }
            for person in people
        ],
        "uploads": [
            {
                "filename": upload["original_filename"],
                "stored_filename": upload["stored_filename"],
            }
            for upload in uploads
        ],
    }


def sqlite_transfer_trip(row: dict[str, Any]) -> dict[str, Any]:
    return _serialize_transfer_trip(row)


def sqlite_tbgn_project(row: dict[str, Any]) -> dict[str, Any]:
    row = dict(row)
    row["geometry"] = json.dumps(parse_tbgn_geometry_text(row["geometry"])) if row.get("geometry") else row.get("geometry")
    return _tbgn_row_to_dict(row)


def normalize_known_segment_difference(
    sqlite_detail: dict[str, Any],
    pg_detail: dict[str, Any],
    valid_segments: set[str],
    comparison: Comparison,
) -> tuple[dict[str, Any], dict[str, Any]]:
    sqlite_copy = json.loads(json.dumps(sqlite_detail))
    pg_copy = json.loads(json.dumps(pg_detail))
    for index, sqlite_target in enumerate(sqlite_copy.get("targets", [])):
        if index >= len(pg_copy.get("targets", [])):
            continue
        pg_target = pg_copy["targets"][index]
        segment_id = sqlite_target.get("segment_id")
        if segment_id and segment_id not in valid_segments and pg_target.get("segment_id") is None:
            comparison.warn(
                f"application {sqlite_copy.get('application_id')} target {index} segment_id",
                f"expected normalization of missing old pixel/KGE segment_id {segment_id!r} to NULL",
            )
            sqlite_target["segment_id"] = None
            if sqlite_target.get("asset_label") == f"Rail segment {segment_id}":
                sqlite_target["asset_label"] = pg_target.get("asset_label")
    return sqlite_copy, pg_copy


def compare_users(sqlite_conn: sqlite3.Connection, pg: PostgresAppQueries, comparison: Comparison) -> None:
    sqlite_count = scalar_sqlite(sqlite_conn, "SELECT COUNT(*) FROM users")
    pg_count = scalar_pg(pg, "SELECT COUNT(*) FROM users")
    comparison.equal("users count", sqlite_count, pg_count)
    for row in rows(sqlite_conn, "SELECT email, password_hash, created_at, is_admin FROM users ORDER BY email"):
        pg_user = pg.get_user_by_email(row["email"])
        expected = dict(row)
        expected["is_admin"] = bool(expected["is_admin"])
        comparison.equal(f"user lookup {row['email']}", expected, pg_user)


def compare_applications(sqlite_conn: sqlite3.Connection, pg: PostgresAppQueries, comparison: Comparison) -> None:
    sqlite_rows = rows(sqlite_conn, "SELECT * FROM applications ORDER BY submitted_at DESC")
    pg_list = pg.list_applications(limit=1000)
    comparison.equal("applications count", len(sqlite_rows), len(pg_list))
    comparison.equal(
        "application list IDs",
        [row["application_id"] for row in sqlite_rows],
        [row["application_id"] for row in pg_list],
    )
    sqlite_pending = rows(sqlite_conn, "SELECT * FROM applications WHERE status = 'submitted' ORDER BY submitted_at DESC")
    pg_pending = pg.list_pending_applications(limit=1000)
    comparison.equal("pending applications count", len(sqlite_pending), len(pg_pending))

    valid_segments = valid_tram_segment_ids(pg)
    for row in sqlite_rows:
        app_id = row["application_id"]
        sqlite_detail = sqlite_application_detail(sqlite_conn, row)
        pg_detail = pg.get_application_detail(app_id)
        if pg_detail is None:
            comparison.fail(f"application detail {app_id}", "missing in PostgreSQL")
            continue
        sqlite_detail, pg_detail = normalize_known_segment_difference(
            sqlite_detail,
            pg_detail,
            valid_segments,
            comparison,
        )
        comparison.equal(f"application detail {app_id}", sqlite_detail, pg_detail)
        comparison.equal(
            f"application_targets {app_id}",
            sqlite_detail["targets"],
            pg_detail["targets"],
        )
        comparison.equal(
            f"application_people {app_id}",
            sqlite_detail["people"],
            pg_detail["people"],
        )
        comparison.equal(
            f"application_uploads {app_id}",
            sqlite_detail["uploads"],
            pg_detail["uploads"],
        )


def compare_transfers(sqlite_conn: sqlite3.Connection, pg: PostgresAppQueries, comparison: Comparison) -> None:
    sqlite_rows = rows(sqlite_conn, "SELECT * FROM transfer_trips ORDER BY submitted_at DESC")
    pg_rows = pg.list_transfer_trips(limit=1000)
    comparison.equal("transfer_trips count", len(sqlite_rows), len(pg_rows))
    comparison.equal(
        "transfer_trip IDs",
        [row["transfer_trip_id"] for row in sqlite_rows],
        [row["transfer_trip_id"] for row in pg_rows],
    )
    sqlite_by_id = {row["transfer_trip_id"]: sqlite_transfer_trip(row) for row in sqlite_rows}
    pg_by_id = {row["transfer_trip_id"]: row for row in pg_rows}
    for trip_id, sqlite_trip in sqlite_by_id.items():
        comparison.equal(f"transfer_trip detail {trip_id}", sqlite_trip, pg_by_id.get(trip_id))
        sqlite_points = rows(
            sqlite_conn,
            """
            SELECT id, transfer_trip_id, point_index, segment_id, lng, lat
            FROM transfer_trip_points
            WHERE transfer_trip_id = ?
            ORDER BY point_index ASC, id ASC
            """,
            (trip_id,),
        )
        pg_points = pg.get_transfer_trip_points(trip_id)
        comparison.equal(f"transfer_trip_points count {trip_id}", len(sqlite_points), len(pg_points))
        comparison.equal(f"transfer_trip_points {trip_id}", sqlite_points, pg_points)


def compare_tbgn(sqlite_conn: sqlite3.Connection, pg: PostgresAppQueries, comparison: Comparison) -> None:
    sqlite_rows = rows(
        sqlite_conn,
        """
        SELECT *
        FROM tbgn_projects
        ORDER BY start_date DESC, end_date DESC, updated_at DESC
        """,
    )
    pg_rows = pg.list_tbgn_projects(limit=1000)
    comparison.equal("tbgn_projects count", len(sqlite_rows), len(pg_rows))
    comparison.equal(
        "tbgn_project IDs",
        [row["id"] for row in sqlite_rows],
        [row["id"] for row in pg_rows],
    )
    sqlite_projects = [sqlite_tbgn_project(row) for row in sqlite_rows]
    comparison.equal("tbgn_projects details", sqlite_projects, pg_rows)


def main() -> int:
    comparison = Comparison()
    try:
        with connect_sqlite() as sqlite_conn, PostgresAppQueries() as pg:
            compare_users(sqlite_conn, pg, comparison)
            compare_applications(sqlite_conn, pg, comparison)
            compare_transfers(sqlite_conn, pg, comparison)
            compare_tbgn(sqlite_conn, pg, comparison)
    except Exception as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    print()
    print(f"warnings: {len(comparison.warnings)}")
    print(f"failures: {len(comparison.failures)}")
    return 1 if comparison.failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
