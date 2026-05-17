from __future__ import annotations

import json
import os
from datetime import date, datetime
from typing import Any

import psycopg
from psycopg.rows import dict_row


def get_database_url() -> str:
    return os.getenv("DATABASE_URL", "").strip()


def connect() -> psycopg.Connection[dict[str, Any]]:
    database_url = get_database_url()
    if not database_url:
        raise RuntimeError("DATABASE_URL is not set")
    return psycopg.connect(database_url, row_factory=dict_row)


def _iso(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    return value


def _date_text(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    raw = str(value).strip()
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00")).date().isoformat()
    except ValueError:
        try:
            return date.fromisoformat(raw[:10]).isoformat()
        except ValueError:
            return None


def _target_attr(target: Any, name: str, default: Any = None) -> Any:
    if isinstance(target, dict):
        return target.get(name, default)
    return getattr(target, name, default)


def is_postgis_wior_available() -> bool:
    return bool(get_postgis_wior_mirror_status().get("available"))


def get_postgis_wior_mirror_status() -> dict[str, Any]:
    status: dict[str, Any] = {
        "database_url_set": bool(get_database_url()),
        "reachable": False,
        "wior_table_exists": False,
        "tram_segments_table_exists": False,
        "row_count": 0,
        "latest_updated_at": None,
        "latest_last_built_at": None,
        "available": False,
        "reason": "database_url_unset",
    }
    if not status["database_url_set"]:
        return status

    try:
        with connect() as conn:
            status["reachable"] = True
            row = conn.execute(
                """
                SELECT
                    to_regclass('public.wior_work_areas') IS NOT NULL AS wior_table_exists,
                    to_regclass('public.tram_segments') IS NOT NULL AS tram_segments_table_exists
                """
            ).fetchone()
            status["wior_table_exists"] = bool(row and row["wior_table_exists"])
            status["tram_segments_table_exists"] = bool(row and row["tram_segments_table_exists"])
            if not status["wior_table_exists"]:
                status["reason"] = "wior_work_areas_missing"
                return status
            if not status["tram_segments_table_exists"]:
                status["reason"] = "tram_segments_missing"
                return status

            column_rows = conn.execute(
                """
                SELECT column_name
                FROM information_schema.columns
                WHERE table_schema = 'public'
                  AND table_name = 'wior_work_areas'
                  AND column_name = ANY(%s)
                """,
                (["updated_at", "last_built_at"],),
            ).fetchall()
            columns = {row["column_name"] for row in column_rows}
            select_parts = ["COUNT(*)::int AS row_count"]
            if "updated_at" in columns:
                select_parts.append("MAX(updated_at) AS latest_updated_at")
            if "last_built_at" in columns:
                select_parts.append("MAX(last_built_at) AS latest_last_built_at")

            mirror_row = conn.execute(
                f"""
                SELECT {", ".join(select_parts)}
                FROM wior_work_areas
                WHERE source = 'wior_sqlite_serving'
                """
            ).fetchone()
            if mirror_row:
                status["row_count"] = int(mirror_row["row_count"] or 0)
                if "latest_updated_at" in mirror_row:
                    status["latest_updated_at"] = _iso(mirror_row["latest_updated_at"])
                if "latest_last_built_at" in mirror_row:
                    status["latest_last_built_at"] = _iso(mirror_row["latest_last_built_at"])

            if status["row_count"] <= 0:
                status["reason"] = "postgis_mirror_empty"
                return status

            status["available"] = True
            status["reason"] = None
            return status
    except Exception as exc:
        status["reason"] = "postgis_mirror_query_failed" if status["reachable"] else "postgis_unreachable"
        status["error_type"] = type(exc).__name__
        return status


def find_wior_near_segments_postgis(
    segment_ids: list[str],
    start_date: str,
    end_date: str,
    buffer_m: float = 10.0,
) -> list[dict[str, Any]]:
    cleaned_segment_ids = sorted({str(item).strip() for item in segment_ids if str(item or "").strip()})
    if not cleaned_segment_ids:
        return []
    start_d = _date_text(start_date)
    end_d = _date_text(end_date)
    if not start_d or not end_d:
        return []
    safe_buffer = max(0.0, min(float(buffer_m), 250.0))

    with connect() as conn:
        rows = conn.execute(
            """
            WITH requested_segments AS (
                SELECT unnest(%s::text[]) AS segment_id
            )
            SELECT DISTINCT ON (w.wior_id, s.segment_id)
                w.wior_id,
                w.wior_reference,
                w.title,
                w.description,
                w.status,
                w.area_type,
                w.start_date,
                w.end_date,
                w.segment_ids,
                s.segment_id AS matched_segment_id,
                ST_Distance(w.geom::geography, s.geom::geography) AS distance_m
            FROM requested_segments r
            JOIN tram_segments s
              ON s.segment_id = r.segment_id
            JOIN wior_work_areas w
              ON w.source = 'wior_sqlite_serving'
             AND w.geom IS NOT NULL
             AND NOT ST_IsEmpty(w.geom)
             AND w.start_date IS NOT NULL
             AND w.end_date IS NOT NULL
             AND w.start_date::date <= %s::date
             AND w.end_date::date >= %s::date
             AND ST_DWithin(w.geom::geography, s.geom::geography, %s)
            ORDER BY w.wior_id, s.segment_id, distance_m ASC
            """,
            (cleaned_segment_ids, end_d, start_d, safe_buffer),
        ).fetchall()
    return [
        {
            "wior_id": row["wior_id"],
            "project_code": row["wior_reference"],
            "project_name": row["title"],
            "description": row["description"],
            "status": row["status"],
            "work_type": row["area_type"],
            "start_date": _iso(row["start_date"]),
            "end_date": _iso(row["end_date"]),
            "matched_segment_id": row["matched_segment_id"],
            "distance_m": float(row["distance_m"]) if row["distance_m"] is not None else None,
            "segment_ids": row["segment_ids"] or [],
        }
        for row in rows
    ]


def find_wior_near_geometry_postgis(
    geojson: dict[str, Any],
    start_date: str,
    end_date: str,
    buffer_m: float = 10.0,
) -> list[dict[str, Any]]:
    start_d = _date_text(start_date)
    end_d = _date_text(end_date)
    if not geojson or not start_d or not end_d:
        return []
    safe_buffer = max(0.0, min(float(buffer_m), 250.0))

    with connect() as conn:
        rows = conn.execute(
            """
            WITH input_geom AS (
                SELECT ST_SetSRID(ST_MakeValid(ST_GeomFromGeoJSON(%s)), 4326) AS geom
            )
            SELECT
                w.wior_id,
                w.wior_reference,
                w.title,
                w.description,
                w.status,
                w.area_type,
                w.start_date,
                w.end_date,
                w.segment_ids,
                ST_Distance(w.geom::geography, input_geom.geom::geography) AS distance_m
            FROM input_geom, wior_work_areas w
            WHERE w.source = 'wior_sqlite_serving'
              AND w.geom IS NOT NULL
              AND NOT ST_IsEmpty(w.geom)
              AND w.start_date IS NOT NULL
              AND w.end_date IS NOT NULL
              AND w.start_date::date <= %s::date
              AND w.end_date::date >= %s::date
              AND ST_DWithin(w.geom::geography, input_geom.geom::geography, %s)
            ORDER BY distance_m ASC
            """,
            (json.dumps(geojson), end_d, start_d, safe_buffer),
        ).fetchall()
    return [
        {
            "wior_id": row["wior_id"],
            "project_code": row["wior_reference"],
            "project_name": row["title"],
            "description": row["description"],
            "status": row["status"],
            "work_type": row["area_type"],
            "start_date": _iso(row["start_date"]),
            "end_date": _iso(row["end_date"]),
            "distance_m": float(row["distance_m"]) if row["distance_m"] is not None else None,
            "segment_ids": row["segment_ids"] or [],
        }
        for row in rows
    ]


def find_wior_conflicts_postgis(
    targets: list[Any],
    buffer_m: float = 10.0,
) -> list[dict[str, Any]]:
    conflicts: list[dict[str, Any]] = []
    for target_index, target in enumerate(targets):
        target_type = str(_target_attr(target, "target_type", "") or "").strip()
        if target_type == "overhead_section":
            continue
        segment_id = str(_target_attr(target, "segment_id", "") or "").strip()
        project_start = _target_attr(target, "project_start")
        project_end = _target_attr(target, "project_end")
        if not segment_id:
            continue

        target_conflicts = find_wior_near_segments_postgis(
            [segment_id],
            str(project_start or ""),
            str(project_end or ""),
            buffer_m=buffer_m,
        )
        resolved_target_index = _target_attr(target, "target_index")
        if resolved_target_index is None:
            resolved_target_index = target_index
        resolved_schedule_index = _target_attr(target, "schedule_index")
        if resolved_schedule_index is None:
            resolved_schedule_index = 0
        resolved_schedule_label = str(_target_attr(target, "schedule_label", "") or "").strip() or "Custom work"

        for wior in target_conflicts:
            conflicts.append(
                {
                    "target_index": resolved_target_index,
                    "schedule_index": resolved_schedule_index,
                    "schedule_label": resolved_schedule_label,
                    "matched_segment_id": wior.get("matched_segment_id") or segment_id,
                    "project_start": project_start,
                    "project_end": project_end,
                    "wior_id": wior.get("wior_id"),
                    "project_code": wior.get("project_code"),
                    "project_name": wior.get("project_name"),
                    "status": wior.get("status"),
                    "work_type": wior.get("work_type"),
                    "start_date": wior.get("start_date"),
                    "end_date": wior.get("end_date"),
                    "distance_m": wior.get("distance_m"),
                }
            )
    return conflicts
