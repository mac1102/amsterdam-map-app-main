from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
from pathlib import Path
from typing import Any

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from shapely.geometry import shape


ROOT = Path(__file__).resolve().parents[1]
WIOR_DB = ROOT / "backend" / "wior.db"


WIOR_SCHEMA_SQL = """
ALTER TABLE wior_work_areas ADD COLUMN IF NOT EXISTS wior_id TEXT;
ALTER TABLE wior_work_areas ADD COLUMN IF NOT EXISTS wior_reference TEXT;
ALTER TABLE wior_work_areas ADD COLUMN IF NOT EXISTS title TEXT;
ALTER TABLE wior_work_areas ADD COLUMN IF NOT EXISTS status TEXT;
ALTER TABLE wior_work_areas ADD COLUMN IF NOT EXISTS start_date TIMESTAMPTZ;
ALTER TABLE wior_work_areas ADD COLUMN IF NOT EXISTS end_date TIMESTAMPTZ;
ALTER TABLE wior_work_areas ADD COLUMN IF NOT EXISTS raw_payload JSONB;
ALTER TABLE wior_work_areas ADD COLUMN IF NOT EXISTS segment_ids JSONB;
ALTER TABLE wior_work_areas ADD COLUMN IF NOT EXISTS is_active BOOLEAN NOT NULL DEFAULT false;
ALTER TABLE wior_work_areas ADD COLUMN IF NOT EXISTS is_upcoming_7d BOOLEAN NOT NULL DEFAULT false;
ALTER TABLE wior_work_areas ADD COLUMN IF NOT EXISTS is_upcoming_30d BOOLEAN NOT NULL DEFAULT false;
ALTER TABLE wior_work_areas ADD COLUMN IF NOT EXISTS is_expired BOOLEAN NOT NULL DEFAULT false;
ALTER TABLE wior_work_areas ADD COLUMN IF NOT EXISTS is_near_tram BOOLEAN NOT NULL DEFAULT false;
ALTER TABLE wior_work_areas ADD COLUMN IF NOT EXISTS last_built_at TIMESTAMPTZ;
ALTER TABLE wior_work_areas ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ DEFAULT now();

CREATE UNIQUE INDEX IF NOT EXISTS wior_work_areas_wior_id_uidx
ON wior_work_areas(wior_id)
WHERE wior_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS wior_work_areas_dates_idx
ON wior_work_areas(start_date, end_date);

CREATE INDEX IF NOT EXISTS wior_work_areas_status_idx
ON wior_work_areas(status);
"""


def database_url() -> str:
    return os.getenv("DATABASE_URL", "").strip()


def connect_sqlite(path: Path) -> sqlite3.Connection:
    if not path.exists():
        raise FileNotFoundError(f"WIOR SQLite cache not found: {path}")
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    return conn


def read_wior_rows(path: Path) -> list[dict[str, Any]]:
    with connect_sqlite(path) as conn:
        rows = conn.execute(
            """
            SELECT
                s.wior_id,
                s.project_code,
                s.project_name,
                s.description,
                s.status,
                s.work_type,
                s.start_date,
                s.end_date,
                s.geometry_type,
                s.geometry_json,
                s.is_active,
                s.is_upcoming_7d,
                s.is_upcoming_30d,
                s.is_expired,
                s.is_near_tram,
                s.segment_ids_json,
                s.last_built_at,
                f.source_payload_json
            FROM wior_features_serving s
            LEFT JOIN wior_features f
              ON f.wior_id = s.wior_id
            ORDER BY s.wior_id
            """
        ).fetchall()
    return [dict(row) for row in rows]


def parse_json_or_none(value: Any) -> Any:
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


def geometry_stats(rows: list[dict[str, Any]]) -> dict[str, int]:
    stats = {
        "total": len(rows),
        "empty_geometry": 0,
        "invalid_json": 0,
        "invalid_shape": 0,
        "unsupported_bounds": 0,
        "valid_or_repairable": 0,
    }
    for row in rows:
        geometry = parse_json_or_none(row.get("geometry_json"))
        if not geometry:
            stats["empty_geometry"] += 1
            continue
        try:
            geom = shape(geometry)
        except Exception:
            stats["invalid_json"] += 1
            continue
        if geom.is_empty:
            stats["empty_geometry"] += 1
            continue
        minx, miny, maxx, maxy = geom.bounds
        if minx < -180 or maxx > 180 or miny < -90 or maxy > 90:
            stats["unsupported_bounds"] += 1
            continue
        if not geom.is_valid:
            stats["invalid_shape"] += 1
        stats["valid_or_repairable"] += 1
    return stats


def ensure_wior_schema(conn: psycopg.Connection[dict[str, Any]]) -> None:
    conn.execute(WIOR_SCHEMA_SQL)


def upsert_rows(conn: psycopg.Connection[dict[str, Any]], rows: list[dict[str, Any]]) -> int:
    inserted = 0
    for row in rows:
        geometry_json = row.get("geometry_json")
        raw_payload = parse_json_or_none(row.get("source_payload_json"))
        if raw_payload is None:
            raw_payload = {
                "wior_id": row.get("wior_id"),
                "project_code": row.get("project_code"),
                "project_name": row.get("project_name"),
                "description": row.get("description"),
                "status": row.get("status"),
                "work_type": row.get("work_type"),
                "start_date": row.get("start_date"),
                "end_date": row.get("end_date"),
                "geometry": parse_json_or_none(geometry_json),
            }
        segment_ids = parse_json_or_none(row.get("segment_ids_json")) or []
        conn.execute(
            """
            INSERT INTO wior_work_areas (
                wior_id,
                wior_reference,
                title,
                source,
                area_type,
                description,
                status,
                start_date,
                end_date,
                raw_payload,
                segment_ids,
                is_active,
                is_upcoming_7d,
                is_upcoming_30d,
                is_expired,
                is_near_tram,
                last_built_at,
                geom,
                updated_at
            )
            VALUES (
                %s, %s, %s, 'wior_sqlite_serving', %s, %s, %s, %s, %s,
                %s, %s, %s, %s, %s, %s, %s, %s,
                ST_SetSRID(ST_MakeValid(ST_GeomFromGeoJSON(%s)), 4326),
                now()
            )
            ON CONFLICT (wior_id)
            WHERE wior_id IS NOT NULL
            DO UPDATE SET
                wior_reference = EXCLUDED.wior_reference,
                title = EXCLUDED.title,
                source = EXCLUDED.source,
                area_type = EXCLUDED.area_type,
                description = EXCLUDED.description,
                status = EXCLUDED.status,
                start_date = EXCLUDED.start_date,
                end_date = EXCLUDED.end_date,
                raw_payload = EXCLUDED.raw_payload,
                segment_ids = EXCLUDED.segment_ids,
                is_active = EXCLUDED.is_active,
                is_upcoming_7d = EXCLUDED.is_upcoming_7d,
                is_upcoming_30d = EXCLUDED.is_upcoming_30d,
                is_expired = EXCLUDED.is_expired,
                is_near_tram = EXCLUDED.is_near_tram,
                last_built_at = EXCLUDED.last_built_at,
                geom = EXCLUDED.geom,
                updated_at = now()
            """,
            (
                row.get("wior_id"),
                row.get("project_code"),
                row.get("project_name"),
                row.get("work_type"),
                row.get("description"),
                row.get("status"),
                row.get("start_date"),
                row.get("end_date"),
                Jsonb(raw_payload),
                Jsonb(segment_ids),
                bool(row.get("is_active")),
                bool(row.get("is_upcoming_7d")),
                bool(row.get("is_upcoming_30d")),
                bool(row.get("is_expired")),
                bool(row.get("is_near_tram")),
                row.get("last_built_at"),
                geometry_json,
            ),
        )
        inserted += 1
    return inserted


def get_postgis_counts(conn: psycopg.Connection[dict[str, Any]]) -> dict[str, Any]:
    queries = [
        ("wior_work_areas_total", "SELECT COUNT(*) FROM wior_work_areas"),
        (
            "wior_sqlite_serving_rows",
            "SELECT COUNT(*) FROM wior_work_areas WHERE source = 'wior_sqlite_serving'",
        ),
        (
            "invalid_wior_geometries",
            "SELECT COUNT(*) FROM wior_work_areas WHERE source = 'wior_sqlite_serving' AND geom IS NOT NULL AND NOT ST_IsValid(geom)",
        ),
        (
            "empty_wior_geometries",
            "SELECT COUNT(*) FROM wior_work_areas WHERE source = 'wior_sqlite_serving' AND (geom IS NULL OR ST_IsEmpty(geom))",
        ),
    ]
    counts: dict[str, Any] = {}
    for key, sql in queries:
        row = conn.execute(sql).fetchone()
        counts[key] = next(iter(row.values())) if row else None
    row = conn.execute(
        """
        SELECT ST_AsText(ST_Extent(geom))
        FROM wior_work_areas
        WHERE source = 'wior_sqlite_serving'
        """
    ).fetchone()
    counts["wior_work_areas_extent"] = next(iter(row.values())) if row else None
    return counts


def print_postgis_counts(counts: dict[str, Any]) -> None:
    labels = [
        ("wior_work_areas total", "wior_work_areas_total"),
        ("wior_sqlite_serving rows", "wior_sqlite_serving_rows"),
        ("invalid WIOR geometries", "invalid_wior_geometries"),
        ("empty WIOR geometries", "empty_wior_geometries"),
    ]
    for label, key in labels:
        print(f"{label}: {counts.get(key)}")
    print(f"wior_work_areas extent: {counts.get('wior_work_areas_extent')}")


def sync_wior_to_postgis(
    apply: bool = False,
    reset_wior_postgis: bool = False,
    dry_run: bool = True,
    wior_db: str | Path | None = None,
) -> dict[str, Any]:
    url = database_url()
    if not url:
        raise RuntimeError("DATABASE_URL is not set")

    should_apply = bool(apply) or not bool(dry_run)
    if reset_wior_postgis and not should_apply:
        raise ValueError("--reset-wior-postgis requires --apply")

    resolved_wior_db = Path(wior_db) if wior_db is not None else WIOR_DB
    rows = read_wior_rows(resolved_wior_db)
    result: dict[str, Any] = {
        "ok": True,
        "apply": should_apply,
        "dry_run": not should_apply,
        "source_wior_db": str(resolved_wior_db),
        "source_serving_rows": len(rows),
        "geometry_stats": geometry_stats(rows),
        "reset_wior_postgis": bool(reset_wior_postgis),
        "deleted_rows": None,
        "rows_upserted": 0,
        "postgis_counts": None,
        "skipped": False,
    }

    if not should_apply:
        return result

    with psycopg.connect(url, row_factory=dict_row) as conn:
        with conn.transaction():
            ensure_wior_schema(conn)
            if reset_wior_postgis:
                result["deleted_rows"] = conn.execute(
                    """
                    DELETE FROM wior_work_areas
                    WHERE source = 'wior_sqlite_serving'
                       OR wior_id IS NOT NULL
                    """
                ).rowcount
            result["rows_upserted"] = upsert_rows(conn, rows)
        result["postgis_counts"] = get_postgis_counts(conn)

    return result


def print_sync_result(result: dict[str, Any]) -> None:
    print(f"Source WIOR SQLite cache: {result['source_wior_db']}")
    print(f"Source serving rows: {result['source_serving_rows']}")
    for key, value in result["geometry_stats"].items():
        print(f"{key}: {value}")

    if result.get("dry_run"):
        print("Dry run only. Pass --apply to write PostGIS WIOR mirror rows.")
        return

    if result.get("deleted_rows") is not None:
        print(f"Deleted existing PostGIS WIOR mirror rows: {result['deleted_rows']}")
    print(f"Rows upserted: {result['rows_upserted']}")
    print_postgis_counts(result.get("postgis_counts") or {})


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Mirror backend/wior.db serving WIOR features into PostGIS.")
    parser.add_argument("--apply", action="store_true", help="Write the WIOR mirror into PostgreSQL.")
    parser.add_argument(
        "--reset-wior-postgis",
        action="store_true",
        help="Delete existing PostGIS WIOR mirror rows before applying.",
    )
    parser.add_argument(
        "--wior-db",
        default=str(WIOR_DB),
        help="Path to backend/wior.db. Defaults to backend/wior.db.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if not database_url():
        print("DATABASE_URL is not set", file=sys.stderr)
        return 2
    if args.reset_wior_postgis and not args.apply:
        print("--reset-wior-postgis requires --apply", file=sys.stderr)
        return 2

    result = sync_wior_to_postgis(
        apply=args.apply,
        reset_wior_postgis=args.reset_wior_postgis,
        dry_run=not args.apply,
        wior_db=args.wior_db,
    )
    print_sync_result(result)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
