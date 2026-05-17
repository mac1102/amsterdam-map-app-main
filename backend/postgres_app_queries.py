from __future__ import annotations

import json
import os
from contextlib import contextmanager
from datetime import date, datetime
from typing import Any, Iterator

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb


VALID_APPLICATION_TARGET_TYPES = {"rail_segment", "switch_junction", "overhead_section"}
TBGN_DEFAULT_COLOR = "#7c3aed"


def get_database_url() -> str:
    return os.getenv("DATABASE_URL", "").strip()


def is_postgres_configured() -> bool:
    return bool(get_database_url())


def connect() -> psycopg.Connection[dict[str, Any]]:
    database_url = get_database_url()
    if not database_url:
        raise RuntimeError("DATABASE_URL is not set")
    return psycopg.connect(database_url, row_factory=dict_row)


@contextmanager
def postgres_app_queries() -> Iterator["PostgresAppQueries"]:
    with PostgresAppQueries() as queries:
        yield queries


def _iso(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    return value


def _row_dict(row: dict[str, Any] | None) -> dict[str, Any] | None:
    if row is None:
        return None
    return {key: _iso(value) for key, value in row.items()}


def _rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [_row_dict(row) or {} for row in rows]


def _normalize_application_target_type(value: Any) -> str:
    target_type = str(value or "rail_segment").strip().lower() or "rail_segment"
    if target_type not in VALID_APPLICATION_TARGET_TYPES:
        return "rail_segment"
    return target_type


def _default_asset_source(target_type: str) -> str:
    if target_type == "overhead_section":
        return "BOVENLEIDING_DATA"
    return "SPOOR_DATA"


def _default_asset_label(target_type: str, asset_id: str, segment_id: str = "") -> str:
    if target_type == "switch_junction":
        return f"Switch/Junction {asset_id or segment_id or '-'}"
    if target_type == "overhead_section":
        return f"Overhead section {asset_id or '-'}"
    return f"Rail segment {segment_id or asset_id or '-'}"


def _parse_json_value(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, (dict, list)):
        return value
    raw = str(value).strip()
    if not raw:
        return None
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return None


def _none_if_empty(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, str):
        stripped = value.strip()
        return stripped or None
    return value


def _admin_application_row_to_summary(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "item_type": "work_application",
        "application_id": row["application_id"],
        "submitted_at": _iso(row["submitted_at"]),
        "status": row["status"],
        "submitted_by_email": row["submitted_by_email"],
        "person_mode": row["person_mode"],
        "work_source": row["work_source"],
        "urgency": row["urgency"],
        "vvw_measure": row["vvw_measure"],
    }


def _serialize_transfer_trip(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "item_type": "transfer_trip",
        "transfer_trip_id": row["transfer_trip_id"],
        "submitted_at": _iso(row["submitted_at"]),
        "status": row["status"],
        "submitted_by_email": row["submitted_by_email"],
        "start_stop_name": row["start_stop_name"],
        "end_stop_name": row["end_stop_name"],
        "start_stop": {
            "id": row["start_stop_id"],
            "name": row["start_stop_name"],
        },
        "end_stop": {
            "id": row["end_stop_id"],
            "name": row["end_stop_name"],
        },
        "planned_date": _iso(row["planned_date"]),
        "planned_start_time": row["planned_start_time"],
        "planned_end_time": row["planned_end_time"],
        "tram_number": row["tram_number"],
        "reason": row["reason"],
        "notes": row["notes"],
        "route_distance_m": row["route_distance_m"],
        "route_geometry": _parse_json_value(row["route_geometry"]),
        "admin_note": row["admin_note"],
        "decision_message": row["decision_message"],
    }


def _tbgn_row_to_dict(row: dict[str, Any], public: bool = False) -> dict[str, Any]:
    data = {
        "id": row["id"],
        "name": row["name"],
        "start_date": _iso(row["start_date"]),
        "end_date": _iso(row["end_date"]),
        "affected_lines": row["affected_lines"] or "",
        "color": row["color"] or TBGN_DEFAULT_COLOR,
        "geometry": _parse_json_value(row["geometry"]),
        "status": row["status"],
        "notes": row["notes"] or "",
    }
    if not public:
        data.update(
            {
                "created_by": row["created_by"] or "",
                "created_at": _iso(row["created_at"]),
                "updated_at": _iso(row["updated_at"]),
            }
        )
    return data


class PostgresAppQueries:
    def __init__(self) -> None:
        self.conn: psycopg.Connection[dict[str, Any]] | None = None

    def __enter__(self) -> "PostgresAppQueries":
        self.conn = connect()
        return self

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
        if self.conn is not None:
            self.conn.close()
            self.conn = None

    def _conn(self) -> psycopg.Connection[dict[str, Any]]:
        if self.conn is None:
            raise RuntimeError("PostgresAppQueries is not connected")
        return self.conn

    def fetchone(self, sql: str, params: tuple[Any, ...] = ()) -> dict[str, Any] | None:
        row = self._conn().execute(sql, params).fetchone()
        return _row_dict(row)

    def fetchall(self, sql: str, params: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
        rows = self._conn().execute(sql, params).fetchall()
        return _rows(rows)

    def get_user_by_email(self, email: str) -> dict[str, Any] | None:
        row = self.fetchone(
            """
            SELECT email, password_hash, created_at, is_admin
            FROM users
            WHERE lower(email) = %s
            """,
            ((email or "").strip().lower(),),
        )
        if row is not None:
            row["is_admin"] = bool(row["is_admin"])
        return row

    def segment_id_if_valid(self, segment_id: str | None) -> str | None:
        candidate = str(segment_id or "").strip()
        if not candidate:
            return None
        row = self.fetchone(
            "SELECT segment_id FROM tram_segments WHERE segment_id = %s",
            (candidate,),
        )
        return row["segment_id"] if row else None

    def find_asset_conflict(
        self,
        target_type: str,
        asset_id: str,
        project_start: str,
        project_end: str,
    ) -> dict[str, Any] | None:
        return self.fetchone(
            """
            SELECT
                a.application_id,
                a.status,
                a.submitted_at,
                a.submitted_by_email,
                t.target_index,
                coalesce(nullif(t.target_type, ''), 'rail_segment') AS target_type,
                coalesce(nullif(t.asset_id, ''), t.segment_id, '') AS asset_id,
                t.asset_label,
                t.asset_source,
                t.segment_id,
                t.line_id,
                t.line_name,
                coalesce(w.project_start, t.project_start) AS project_start,
                coalesce(w.project_end, t.project_end) AS project_end,
                w.window_index AS schedule_index,
                w.label AS schedule_label
            FROM applications a
            JOIN application_targets t
              ON t.application_id = a.application_id
            LEFT JOIN application_target_windows w
              ON w.target_id = t.id
            WHERE coalesce(nullif(t.target_type, ''), 'rail_segment') = %s
              AND coalesce(nullif(t.asset_id, ''), t.segment_id, '') = %s
              AND coalesce(w.project_start, t.project_start) < %s
              AND coalesce(w.project_end, t.project_end) > %s
            ORDER BY coalesce(w.project_start, t.project_start) ASC
            LIMIT 1
            """,
            (target_type, asset_id, project_end, project_start),
        )

    def list_line_status_applications(self, email: str, line_id: str) -> list[dict[str, Any]]:
        return self.fetchall(
            """
            SELECT a.application_id, a.submitted_at, a.status,
                   t.line_id, t.line_name, t.project_start, t.project_end, t.segment_id
            FROM applications a
            JOIN application_targets t ON t.application_id = a.application_id
            WHERE lower(a.submitted_by_email) = %s AND coalesce(t.line_id, '') = %s
            ORDER BY a.submitted_at DESC
            """,
            ((email or "").strip().lower(), line_id),
        )

    def list_segment_bookings(
        self,
        target_type: str,
        asset_id: str,
        range_start: str,
        range_end: str,
    ) -> list[dict[str, Any]]:
        return self.fetchall(
            """
            SELECT
                a.status,
                coalesce(nullif(t.target_type, ''), 'rail_segment') AS target_type,
                coalesce(nullif(t.asset_id, ''), t.segment_id, '') AS asset_id,
                t.asset_label,
                t.asset_source,
                t.segment_id,
                t.line_id,
                t.line_name,
                coalesce(w.project_start, t.project_start) AS project_start,
                coalesce(w.project_end, t.project_end) AS project_end,
                w.label AS schedule_label,
                w.window_index AS schedule_index
            FROM applications a
            JOIN application_targets t
              ON t.application_id = a.application_id
            LEFT JOIN application_target_windows w
              ON w.target_id = t.id
            WHERE coalesce(nullif(t.target_type, ''), 'rail_segment') = %s
              AND coalesce(nullif(t.asset_id, ''), t.segment_id, '') = %s
              AND coalesce(w.project_start, t.project_start) < %s
              AND coalesce(w.project_end, t.project_end) > %s
            ORDER BY coalesce(w.project_start, t.project_start) ASC
            """,
            (target_type, asset_id, range_end, range_start),
        )

    def list_applications(
        self,
        status: str | None = None,
        email: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        params: list[Any] = []
        sql = "SELECT * FROM applications WHERE 1=1"
        if status:
            sql += " AND status = %s"
            params.append(status.strip())
        if email:
            sql += " AND lower(submitted_by_email) LIKE %s"
            params.append(f"%{email.strip().lower()}%")
        sql += " ORDER BY submitted_at DESC LIMIT %s"
        params.append(max(1, int(limit)))
        rows = self.fetchall(sql, tuple(params))
        return [_admin_application_row_to_summary(row) for row in rows]

    def list_pending_applications(self, limit: int = 100) -> list[dict[str, Any]]:
        return self.list_applications(status="submitted", limit=limit)

    def list_applications_for_email(self, email: str) -> list[dict[str, Any]]:
        rows = self.fetchall(
            """
            SELECT *
            FROM applications
            WHERE lower(submitted_by_email) = %s
            ORDER BY submitted_at DESC
            """,
            ((email or "").strip().lower(),),
        )
        return [self.serialize_application_summary(row) for row in rows]

    def get_application_detail(self, application_id: str) -> dict[str, Any] | None:
        row = self.fetchone(
            "SELECT * FROM applications WHERE application_id = %s",
            (application_id,),
        )
        if row is None:
            return None
        return self.serialize_application_summary(row)

    def get_application_targets(self, application_id: str) -> list[dict[str, Any]]:
        return self.fetchall(
            """
            SELECT id, target_index,
                   coalesce(nullif(target_type, ''), 'rail_segment') AS target_type,
                   coalesce(nullif(asset_id, ''), segment_id, '') AS asset_id,
                   asset_label, asset_source,
                   segment_id, line_id, line_name, work_mode,
                   work_start_x, work_start_y, work_end_x, work_end_y,
                   project_start, project_end
            FROM application_targets
            WHERE application_id = %s
            ORDER BY target_index ASC
            """,
            (application_id,),
        )

    def get_application_target_windows(self, application_id: str) -> list[dict[str, Any]]:
        return self.fetchall(
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
            WHERE t.application_id = %s
            ORDER BY t.target_index ASC, w.window_index ASC
            """,
            (application_id,),
        )

    def get_application_people(self, application_id: str) -> list[dict[str, Any]]:
        return self.fetchall(
            """
            SELECT target_index, first_name, last_name, phone, email, employee_id
            FROM application_people
            WHERE application_id = %s
            ORDER BY CASE WHEN target_index IS NULL THEN -1 ELSE target_index END ASC
            """,
            (application_id,),
        )

    def get_application_uploads(self, application_id: str) -> list[dict[str, Any]]:
        return self.fetchall(
            """
            SELECT original_filename, stored_filename
            FROM application_uploads
            WHERE application_id = %s
            ORDER BY id ASC
            """,
            (application_id,),
        )

    def create_application(
        self,
        application_id: str,
        submitted_at: str,
        submitted_by_email: str,
        person_mode: str,
        work_details: dict[str, Any],
        contact_details: dict[str, Any],
        targets: list[dict[str, Any]],
        people: list[dict[str, Any]],
        uploads: list[dict[str, Any]],
    ) -> None:
        conn = self._conn()
        project_starts = [target.get("project_start") for target in targets if target.get("project_start")]
        project_ends = [target.get("project_end") for target in targets if target.get("project_end")]
        project_start = min(project_starts) if project_starts else None
        project_end = max(project_ends) if project_ends else None

        with conn.transaction():
            conn.execute(
                """
                INSERT INTO applications (
                    application_id, submitted_at, status, submitted_by_email, person_mode,
                    work_description, work_source, urgency, affected_lines, work_notes,
                    coordinator, vvw_measure, project_start, project_end
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    application_id,
                    submitted_at,
                    "submitted",
                    submitted_by_email,
                    person_mode,
                    work_details.get("description"),
                    work_details.get("source"),
                    work_details.get("urgency"),
                    work_details.get("affected_lines"),
                    work_details.get("notes"),
                    contact_details.get("coordinator"),
                    contact_details.get("vvw_measure"),
                    project_start,
                    project_end,
                ),
            )

            for index, target in enumerate(targets):
                work_start = target.get("work_start_point") or {}
                work_end = target.get("work_end_point") or {}
                valid_segment_id = self.segment_id_if_valid(target.get("segment_id"))
                inserted = conn.execute(
                    """
                    INSERT INTO application_targets (
                        application_id, target_index, target_type, asset_id, asset_label, asset_source,
                        segment_id, line_id, line_name,
                        work_mode, work_start_x, work_start_y, work_end_x, work_end_y,
                        project_start, project_end
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    RETURNING id
                    """,
                    (
                        application_id,
                        index,
                        target["target_type"],
                        _none_if_empty(target.get("asset_id")),
                        _none_if_empty(target.get("asset_label")),
                        _none_if_empty(target.get("asset_source")),
                        valid_segment_id,
                        _none_if_empty(target.get("line_id")),
                        _none_if_empty(target.get("line_name")),
                        target["work_mode"],
                        work_start.get("x"),
                        work_start.get("y"),
                        work_end.get("x"),
                        work_end.get("y"),
                        target["project_start"],
                        target["project_end"],
                    ),
                ).fetchone()
                target_row_id = inserted["id"]

                for schedule_index, schedule in enumerate(target.get("schedules") or []):
                    conn.execute(
                        """
                        INSERT INTO application_target_windows (
                            target_id, window_index, project_start, project_end, label
                        )
                        VALUES (%s, %s, %s, %s, %s)
                        """,
                        (
                            target_row_id,
                            schedule_index,
                            schedule.get("project_start"),
                            schedule.get("project_end"),
                            schedule.get("label") or "Custom work",
                        ),
                    )

            for person in people:
                conn.execute(
                    """
                    INSERT INTO application_people (
                        application_id, target_index, first_name, last_name, phone, email, employee_id
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        application_id,
                        person.get("target_index"),
                        person["first_name"],
                        person["last_name"],
                        person["phone"],
                        person["email"],
                        _none_if_empty(person.get("employee_id")),
                    ),
                )

            for upload in uploads:
                conn.execute(
                    """
                    INSERT INTO application_uploads (
                        application_id, original_filename, stored_filename, created_at
                    )
                    VALUES (%s, %s, %s, %s)
                    """,
                    (
                        application_id,
                        upload["filename"],
                        upload["stored_filename"],
                        submitted_at,
                    ),
                )

    def update_application_status(
        self,
        application_id: str,
        status: str,
        admin_note: str,
        decision_message: str,
    ) -> bool:
        with self._conn().transaction():
            row = self._conn().execute(
                """
                UPDATE applications
                SET status = %s, admin_note = %s, decision_message = %s
                WHERE application_id = %s
                RETURNING application_id
                """,
                (status, admin_note, decision_message, application_id),
            ).fetchone()
        return row is not None

    def get_application_upload_filenames(self, application_id: str) -> list[str]:
        rows = self.fetchall(
            """
            SELECT stored_filename
            FROM application_uploads
            WHERE application_id = %s
            ORDER BY id ASC
            """,
            (application_id,),
        )
        return [str(row["stored_filename"]) for row in rows if row.get("stored_filename")]

    def delete_application(self, application_id: str) -> bool:
        with self._conn().transaction():
            row = self._conn().execute(
                "DELETE FROM applications WHERE application_id = %s RETURNING application_id",
                (application_id,),
            ).fetchone()
        return row is not None

    def serialize_application_summary(self, row: dict[str, Any]) -> dict[str, Any]:
        application_id = row["application_id"]
        targets = self.get_application_targets(application_id)
        target_windows = self.get_application_target_windows(application_id)
        people = self.get_application_people(application_id)
        uploads = self.get_application_uploads(application_id)

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

    def list_transfer_trips(
        self,
        status: str | None = None,
        email: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        params: list[Any] = []
        sql = "SELECT * FROM transfer_trips WHERE 1=1"
        if status:
            sql += " AND status = %s"
            params.append(status.strip())
        if email:
            sql += " AND lower(submitted_by_email) LIKE %s"
            params.append(f"%{email.strip().lower()}%")
        sql += " ORDER BY submitted_at DESC LIMIT %s"
        params.append(max(1, int(limit)))
        rows = self.fetchall(sql, tuple(params))
        return [_serialize_transfer_trip(row) for row in rows]

    def list_transfer_trips_for_email(self, email: str, limit: int = 100) -> list[dict[str, Any]]:
        rows = self.fetchall(
            """
            SELECT *
            FROM transfer_trips
            WHERE lower(submitted_by_email) = %s
            ORDER BY submitted_at DESC
            LIMIT %s
            """,
            ((email or "").strip().lower(), max(1, int(limit))),
        )
        return [_serialize_transfer_trip(row) for row in rows]

    def get_transfer_trip_detail(self, trip_id: str) -> dict[str, Any] | None:
        row = self.fetchone(
            "SELECT * FROM transfer_trips WHERE transfer_trip_id = %s",
            (trip_id,),
        )
        if row is None:
            return None
        return _serialize_transfer_trip(row)

    def get_transfer_trip_points(self, trip_id: str) -> list[dict[str, Any]]:
        return self.fetchall(
            """
            SELECT id, transfer_trip_id, point_index, segment_id, lng, lat
            FROM transfer_trip_points
            WHERE transfer_trip_id = %s
            ORDER BY point_index ASC, id ASC
            """,
            (trip_id,),
        )

    def create_transfer_trip(
        self,
        transfer_trip_id: str,
        submitted_at: str,
        submitted_by_email: str,
        start_stop_id: int,
        start_stop_name: str,
        end_stop_id: int,
        end_stop_name: str,
        planned_date: str,
        planned_start_time: str,
        planned_end_time: str,
        tram_number: str | None,
        reason: str | None,
        notes: str | None,
        route_distance_m: float | None,
        route_geometry: dict[str, Any] | None,
        points: list[dict[str, Any]],
    ) -> None:
        with self._conn().transaction():
            self._conn().execute(
                """
                INSERT INTO transfer_trips (
                    transfer_trip_id, submitted_at, status, submitted_by_email,
                    start_stop_id, start_stop_name, end_stop_id, end_stop_name,
                    planned_date, planned_start_time, planned_end_time,
                    tram_number, reason, notes,
                    route_distance_m, route_geometry
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    transfer_trip_id,
                    submitted_at,
                    "submitted",
                    submitted_by_email,
                    start_stop_id,
                    start_stop_name,
                    end_stop_id,
                    end_stop_name,
                    planned_date,
                    planned_start_time,
                    planned_end_time,
                    tram_number,
                    reason,
                    notes,
                    route_distance_m,
                    Jsonb(route_geometry) if route_geometry is not None else None,
                ),
            )

            for point in points:
                self._conn().execute(
                    """
                    INSERT INTO transfer_trip_points (
                        transfer_trip_id, point_index, segment_id, lng, lat
                    )
                    VALUES (%s, %s, %s, %s, %s)
                    """,
                    (
                        transfer_trip_id,
                        point["point_index"],
                        self.segment_id_if_valid(point.get("segment_id")),
                        point["lng"],
                        point["lat"],
                    ),
                )

    def update_transfer_trip_status(
        self,
        transfer_trip_id: str,
        status: str,
        admin_note: str,
        decision_message: str,
    ) -> bool:
        with self._conn().transaction():
            row = self._conn().execute(
                """
                UPDATE transfer_trips
                SET status = %s, admin_note = %s, decision_message = %s
                WHERE transfer_trip_id = %s
                RETURNING transfer_trip_id
                """,
                (status, admin_note, decision_message, transfer_trip_id),
            ).fetchone()
        return row is not None

    def delete_transfer_trip(self, transfer_trip_id: str) -> bool:
        with self._conn().transaction():
            row = self._conn().execute(
                "DELETE FROM transfer_trips WHERE transfer_trip_id = %s RETURNING transfer_trip_id",
                (transfer_trip_id,),
            ).fetchone()
        return row is not None

    def list_tbgn_projects(
        self,
        limit: int = 100,
        public: bool = False,
        published_only: bool = False,
    ) -> list[dict[str, Any]]:
        if published_only:
            sql = """
                SELECT *
                FROM tbgn_projects
                WHERE status = 'published'
                ORDER BY start_date ASC, end_date ASC, name ASC
                LIMIT %s
            """
        else:
            sql = """
                SELECT *
                FROM tbgn_projects
                ORDER BY start_date DESC, end_date DESC, updated_at DESC
                LIMIT %s
            """
        rows = self.fetchall(
            sql,
            (max(1, int(limit)),),
        )
        return [_tbgn_row_to_dict(row, public=public) for row in rows]

    def get_tbgn_project(self, project_id: str, public: bool = False) -> dict[str, Any] | None:
        row = self.fetchone(
            "SELECT * FROM tbgn_projects WHERE id = %s",
            (project_id,),
        )
        if row is None:
            return None
        return _tbgn_row_to_dict(row, public=public)

    def create_tbgn_project(
        self,
        project_id: str,
        payload: dict[str, Any],
        created_by: str,
        created_at: str,
    ) -> dict[str, Any]:
        with self._conn().transaction():
            row = self._conn().execute(
                """
                INSERT INTO tbgn_projects (
                    id, name, start_date, end_date, affected_lines, color, geometry,
                    status, notes, created_by, created_at, updated_at
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING *
                """,
                (
                    project_id,
                    payload["name"],
                    payload["start_date"],
                    payload["end_date"],
                    payload["affected_lines"],
                    payload["color"],
                    payload["geometry"],
                    payload["status"],
                    payload["notes"],
                    created_by,
                    created_at,
                    created_at,
                ),
            ).fetchone()
        return _tbgn_row_to_dict(_row_dict(row) or {})

    def update_tbgn_project(
        self,
        project_id: str,
        payload: dict[str, Any],
        updated_at: str,
    ) -> dict[str, Any] | None:
        with self._conn().transaction():
            row = self._conn().execute(
                """
                UPDATE tbgn_projects
                SET name = %s,
                    start_date = %s,
                    end_date = %s,
                    affected_lines = %s,
                    color = %s,
                    geometry = %s,
                    status = %s,
                    notes = %s,
                    updated_at = %s
                WHERE id = %s
                RETURNING *
                """,
                (
                    payload["name"],
                    payload["start_date"],
                    payload["end_date"],
                    payload["affected_lines"],
                    payload["color"],
                    payload["geometry"],
                    payload["status"],
                    payload["notes"],
                    updated_at,
                    project_id,
                ),
            ).fetchone()
        if row is None:
            return None
        return _tbgn_row_to_dict(_row_dict(row) or {})

    def delete_tbgn_project(self, project_id: str) -> bool:
        with self._conn().transaction():
            row = self._conn().execute(
                "DELETE FROM tbgn_projects WHERE id = %s RETURNING id",
                (project_id,),
            ).fetchone()
        return row is not None


def _with_queries(method_name: str, *args: Any, **kwargs: Any) -> Any:
    if not is_postgres_configured():
        return None
    try:
        with PostgresAppQueries() as queries:
            method = getattr(queries, method_name)
            return method(*args, **kwargs)
    except Exception:
        return None


def get_user_by_email_pg(email: str) -> dict[str, Any] | None:
    return _with_queries("get_user_by_email", email)


def list_applications_pg(
    status: str | None = None,
    email: str | None = None,
    limit: int = 100,
) -> list[dict[str, Any]] | None:
    return _with_queries("list_applications", status=status, email=email, limit=limit)


def list_pending_applications_pg(limit: int = 100) -> list[dict[str, Any]] | None:
    return _with_queries("list_pending_applications", limit=limit)


def get_application_detail_pg(application_id: str) -> dict[str, Any] | None:
    return _with_queries("get_application_detail", application_id)


def list_applications_for_email_pg(email: str) -> list[dict[str, Any]] | None:
    return _with_queries("list_applications_for_email", email)


def get_application_targets_pg(application_id: str) -> list[dict[str, Any]] | None:
    return _with_queries("get_application_targets", application_id)


def get_application_people_pg(application_id: str) -> list[dict[str, Any]] | None:
    return _with_queries("get_application_people", application_id)


def get_application_uploads_pg(application_id: str) -> list[dict[str, Any]] | None:
    return _with_queries("get_application_uploads", application_id)


def list_transfer_trips_pg(
    status: str | None = None,
    email: str | None = None,
    limit: int = 100,
) -> list[dict[str, Any]] | None:
    return _with_queries("list_transfer_trips", status=status, email=email, limit=limit)


def list_transfer_trips_for_email_pg(email: str, limit: int = 100) -> list[dict[str, Any]] | None:
    return _with_queries("list_transfer_trips_for_email", email, limit=limit)


def get_transfer_trip_detail_pg(trip_id: str) -> dict[str, Any] | None:
    return _with_queries("get_transfer_trip_detail", trip_id)


def get_transfer_trip_points_pg(trip_id: str) -> list[dict[str, Any]] | None:
    return _with_queries("get_transfer_trip_points", trip_id)


def list_tbgn_projects_pg(
    limit: int = 100,
    public: bool = False,
    published_only: bool = False,
) -> list[dict[str, Any]] | None:
    return _with_queries(
        "list_tbgn_projects",
        limit=limit,
        public=public,
        published_only=published_only,
    )


def get_tbgn_project_pg(project_id: str, public: bool = False) -> dict[str, Any] | None:
    return _with_queries("get_tbgn_project", project_id, public=public)
