from __future__ import annotations

import json
import sqlite3
import threading
from datetime import datetime, timezone, date, timedelta
from pathlib import Path
from urllib.request import urlopen

from pyproj import Transformer
from shapely.geometry import shape
from shapely.ops import transform, unary_union

BASE_DIR = Path(__file__).resolve().parent
WIOR_DB_PATH = BASE_DIR / "wior.db"
WIOR_API_URL = "https://api.data.amsterdam.nl/v1/wior/wior/?_format=geojson"

TRAM_TRACKS_GEOJSON_PATH = BASE_DIR / "data" / "tram_tracks.geojson"
SPOOR_SEGMENTS_GEOJSON_PATH = BASE_DIR / "data" / "spoor_segments.geojson"

TRAM_BUFFER_METERS = 10.0
SEGMENT_MATCH_BUFFER_METERS = 2.0

# Input geometries are assumed to be WGS84 and transformed to RD for metric operations
WGS84_TO_RD = Transformer.from_crs("EPSG:4326", "EPSG:28992", always_xy=True)

# Single-process refresh lock
_wior_refresh_lock = threading.Lock()


def get_wior_db() -> sqlite3.Connection:
    conn = sqlite3.connect(WIOR_DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout = 5000")
    return conn


def init_wior_db() -> None:
    conn = get_wior_db()
    try:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS wior_sync_runs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                started_at TEXT NOT NULL,
                finished_at TEXT,
                status TEXT NOT NULL,
                records_fetched INTEGER DEFAULT 0,
                records_loaded INTEGER DEFAULT 0,
                error_message TEXT
            );

            CREATE TABLE IF NOT EXISTS wior_features (
                wior_id TEXT PRIMARY KEY,
                project_code TEXT,
                project_name TEXT,
                description TEXT,
                status TEXT,
                work_type TEXT,
                start_date TEXT,
                end_date TEXT,
                geometry_type TEXT,
                geometry_json TEXT NOT NULL,
                source_payload_json TEXT,
                last_synced_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS wior_features_serving (
                wior_id TEXT PRIMARY KEY,
                project_code TEXT,
                project_name TEXT,
                description TEXT,
                status TEXT,
                work_type TEXT,
                start_date TEXT,
                end_date TEXT,
                geometry_type TEXT,
                geometry_json TEXT NOT NULL,
                is_active INTEGER NOT NULL DEFAULT 0,
                is_upcoming_7d INTEGER NOT NULL DEFAULT 0,
                is_upcoming_30d INTEGER NOT NULL DEFAULT 0,
                is_expired INTEGER NOT NULL DEFAULT 0,
                is_near_tram INTEGER NOT NULL DEFAULT 0,
                segment_ids_json TEXT,
                last_built_at TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_wior_serving_active
            ON wior_features_serving(is_active);

            CREATE INDEX IF NOT EXISTS idx_wior_serving_next7
            ON wior_features_serving(is_upcoming_7d);

            CREATE INDEX IF NOT EXISTS idx_wior_serving_next30
            ON wior_features_serving(is_upcoming_30d);

            CREATE INDEX IF NOT EXISTS idx_wior_serving_near_tram
            ON wior_features_serving(is_near_tram);

            CREATE INDEX IF NOT EXISTS idx_wior_features_end_date
            ON wior_features(end_date);
            """
        )
        conn.commit()
    finally:
        conn.close()


def fetch_wior_raw() -> dict:
    import time
    from urllib.request import Request

    for attempt in range(3):
        try:
            req = Request(
                WIOR_API_URL,
                headers={"User-Agent": "gvb-tram-communication-map/1.0"},
            )
            with urlopen(req, timeout=60) as response:
                raw = response.read()
                return json.loads(raw)
        except Exception as exc:
            if attempt < 2:
                time.sleep(2)
            else:
                raise RuntimeError(f"Failed to fetch WIOR API after 3 attempts: {exc}") from exc


def _parse_date_safe(value: str | None) -> date | None:
    if not value:
        return None

    raw = str(value).strip()
    if not raw:
        return None

    try:
        return date.fromisoformat(raw[:10])
    except Exception:
        return None


def _compute_flags(start_date_str: str | None, end_date_str: str | None, today: date) -> dict:
    start_d = _parse_date_safe(start_date_str)
    end_d = _parse_date_safe(end_date_str)

    horizon_7_end = today + timedelta(days=7)
    horizon_30_end = today + timedelta(days=30)

    is_active = 0
    is_upcoming_7d = 0
    is_upcoming_30d = 0
    is_expired = 0

    if start_d and end_d:
        if start_d <= today <= end_d:
            is_active = 1

        if end_d < today:
            is_expired = 1

        # Overlaps [today, today+7]
        if start_d <= horizon_7_end and end_d >= today:
            is_upcoming_7d = 1

        # Overlaps [today, today+30]
        if start_d <= horizon_30_end and end_d >= today:
            is_upcoming_30d = 1

    elif start_d:
        if today <= start_d <= horizon_7_end:
            is_upcoming_7d = 1

        if today <= start_d <= horizon_30_end:
            is_upcoming_30d = 1

    return {
        "is_active": is_active,
        "is_upcoming_7d": is_upcoming_7d,
        "is_upcoming_30d": is_upcoming_30d,
        "is_expired": is_expired,
    }


def safe_shape(geometry: dict):
    try:
        geom = shape(geometry)
    except Exception:
        return None

    if geom.is_empty:
        return None

    if not geom.is_valid:
        geom = geom.buffer(0)

    if geom.is_empty:
        return None

    return geom


def _load_tram_corridor_rd():
    if not TRAM_TRACKS_GEOJSON_PATH.exists():
        raise FileNotFoundError(
            f"Tram tracks GeoJSON not found: {TRAM_TRACKS_GEOJSON_PATH}"
        )

    raw_text = TRAM_TRACKS_GEOJSON_PATH.read_text(encoding="utf-8", errors="replace").strip()
    if not raw_text:
        raise RuntimeError(
            f"Tram tracks GeoJSON is empty: {TRAM_TRACKS_GEOJSON_PATH}"
        )

    try:
        payload = json.loads(raw_text)
    except Exception as exc:
        preview = raw_text[:120]
        raise RuntimeError(
            f"Invalid tram_tracks.geojson JSON. First 120 chars: {preview!r}"
        ) from exc

    features = payload.get("features", []) or []
    tram_geoms_rd = []

    for feature in features:
        geometry = feature.get("geometry")
        if not geometry:
            continue

        geom = safe_shape(geometry)
        if geom is None:
            continue

        if geom.geom_type not in {"LineString", "MultiLineString"}:
            continue

        geom_rd = transform(WGS84_TO_RD.transform, geom)
        if not geom_rd.is_valid:
            geom_rd = geom_rd.buffer(0)

        if not geom_rd.is_empty:
            tram_geoms_rd.append(geom_rd)

    if not tram_geoms_rd:
        raise RuntimeError("No usable tram geometries found in tram_tracks.geojson")

    tram_union_rd = unary_union(tram_geoms_rd)
    tram_corridor_rd = tram_union_rd.buffer(TRAM_BUFFER_METERS)
    return tram_corridor_rd


def _load_spoor_segment_index_rd():
    if not SPOOR_SEGMENTS_GEOJSON_PATH.exists():
        raise FileNotFoundError(
            f"Spoor segments GeoJSON not found: {SPOOR_SEGMENTS_GEOJSON_PATH}"
        )

    raw_text = SPOOR_SEGMENTS_GEOJSON_PATH.read_text(encoding="utf-8", errors="replace").strip()
    if not raw_text:
        raise RuntimeError(
            f"Spoor segments GeoJSON is empty: {SPOOR_SEGMENTS_GEOJSON_PATH}"
        )

    try:
        payload = json.loads(raw_text)
    except Exception as exc:
        preview = raw_text[:120]
        raise RuntimeError(
            f"Invalid spoor_segments.geojson JSON. First 120 chars: {preview!r}"
        ) from exc

    features = payload.get("features", []) or []
    segment_index = []

    for feature in features:
        props = feature.get("properties", {}) or {}
        geometry = feature.get("geometry") or {}

        segment_id = props.get("segment_id")
        if not segment_id:
            continue

        geom = safe_shape(geometry)
        if geom is None:
            continue

        geom_rd = transform(WGS84_TO_RD.transform, geom)
        if not geom_rd.is_valid:
            geom_rd = geom_rd.buffer(0)

        if geom_rd.is_empty:
            continue

        segment_index.append(
            {
                "segment_id": str(segment_id),
                "line_id": props.get("line_id"),
                "line_name": props.get("line_name"),
                "geom_rd": geom_rd.buffer(SEGMENT_MATCH_BUFFER_METERS),
            }
        )

    if not segment_index:
        raise RuntimeError("No usable segment geometries found in spoor_segments.geojson")

    return segment_index


def _wior_geometry_is_near_tram(geometry_json: str, tram_corridor_rd) -> bool:
    if not geometry_json:
        return False

    try:
        geometry_obj = json.loads(geometry_json)
        geom = shape(geometry_obj)
    except Exception:
        return False

    if geom.is_empty:
        return False

    if not geom.is_valid:
        geom = geom.buffer(0)

    geom_rd = transform(WGS84_TO_RD.transform, geom)

    if not geom_rd.is_valid:
        geom_rd = geom_rd.buffer(0)

    return geom_rd.intersects(tram_corridor_rd)


def _find_matching_segment_ids(geometry_json: str, spoor_segment_index) -> list[str]:
    if not geometry_json:
        return []

    try:
        geometry_obj = json.loads(geometry_json)
        geom = shape(geometry_obj)
    except Exception:
        return []

    if geom.is_empty:
        return []

    if not geom.is_valid:
        geom = geom.buffer(0)

    geom_rd = transform(WGS84_TO_RD.transform, geom)
    if not geom_rd.is_valid:
        geom_rd = geom_rd.buffer(0)

    if geom_rd.is_empty:
        return []

    matched_ids = []

    for item in spoor_segment_index:
        try:
            if geom_rd.intersects(item["geom_rd"]):
                matched_ids.append(item["segment_id"])
        except Exception:
            continue

    return sorted(set(matched_ids))


def normalize_feature(feature: dict, synced_at: str) -> dict:
    props = feature.get("properties", {}) or {}
    geometry = feature.get("geometry", {}) or {}

    wior_id = str(feature.get("id") or props.get("id") or "").strip()

    return {
        "wior_id": wior_id,
        "project_code": props.get("wiorNummer"),
        "project_name": props.get("projectnaam"),
        "description": props.get("beschrijving"),
        "status": props.get("hoofdstatus"),
        "work_type": props.get("typeWerkzaamheden"),
        "start_date": props.get("datumStartUitvoering"),
        "end_date": props.get("datumEindeUitvoering"),
        "geometry_type": geometry.get("type"),
        "geometry_json": json.dumps(geometry, ensure_ascii=False),
        "source_payload_json": json.dumps(feature, ensure_ascii=False),
        "last_synced_at": synced_at,
    }


def _cleanup_expired_source_rows(cur: sqlite3.Cursor, today: date) -> None:
    cur.execute(
        """
        DELETE FROM wior_features
        WHERE end_date IS NOT NULL
          AND substr(end_date, 1, 10) < ?
        """,
        (today.isoformat(),)
    )


def _rebuild_wior_serving_table(
    cur: sqlite3.Cursor,
    built_at: str,
    today: date,
    tram_corridor_rd,
    spoor_segment_index,
) -> int:
    rows = cur.execute(
        """
        SELECT
            wior_id, project_code, project_name, description, status,
            work_type, start_date, end_date, geometry_type, geometry_json
        FROM wior_features
        """
    ).fetchall()

    cur.execute("DELETE FROM wior_features_serving")

    inserted = 0

    for row in rows:
        is_near_tram = 1 if _wior_geometry_is_near_tram(row["geometry_json"], tram_corridor_rd) else 0
        if not is_near_tram:
            continue

        matched_segment_ids = _find_matching_segment_ids(
            row["geometry_json"],
            spoor_segment_index,
        )

        flags = _compute_flags(row["start_date"], row["end_date"], today)

        cur.execute(
            """
            INSERT INTO wior_features_serving (
                wior_id, project_code, project_name, description, status,
                work_type, start_date, end_date, geometry_type, geometry_json,
                is_active, is_upcoming_7d, is_upcoming_30d, is_expired,
                is_near_tram, segment_ids_json, last_built_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                row["wior_id"],
                row["project_code"],
                row["project_name"],
                row["description"],
                row["status"],
                row["work_type"],
                row["start_date"],
                row["end_date"],
                row["geometry_type"],
                row["geometry_json"],
                flags["is_active"],
                flags["is_upcoming_7d"],
                flags["is_upcoming_30d"],
                flags["is_expired"],
                is_near_tram,
                json.dumps(matched_segment_ids, ensure_ascii=False),
                built_at,
            )
        )
        inserted += 1

    return inserted


def refresh_wior_safely() -> dict:
    if not _wior_refresh_lock.acquire(blocking=False):
        return {
            "ok": False,
            "skipped": True,
            "reason": "refresh already running",
        }

    conn = get_wior_db()
    sync_run_id = None

    try:
        started_at = datetime.now(timezone.utc).isoformat()
        synced_at = started_at
        today = datetime.now(timezone.utc).date()

        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO wior_sync_runs (started_at, status)
            VALUES (?, ?)
            """,
            (started_at, "running")
        )
        sync_run_id = cur.lastrowid
        conn.commit()

        raw = fetch_wior_raw()
        features = raw.get("features", []) or []

        normalized_rows = []
        for feature in features:
            row = normalize_feature(feature, synced_at)
            if row["wior_id"]:
                normalized_rows.append(row)

        tram_corridor_rd = _load_tram_corridor_rd()
        spoor_segment_index = _load_spoor_segment_index_rd()

        conn.execute("BEGIN")
        cur = conn.cursor()

        cur.execute("DELETE FROM wior_features")

        loaded = 0
        for row in normalized_rows:
            cur.execute(
                """
                INSERT INTO wior_features (
                    wior_id, project_code, project_name, description, status,
                    work_type, start_date, end_date, geometry_type,
                    geometry_json, source_payload_json, last_synced_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    row["wior_id"],
                    row["project_code"],
                    row["project_name"],
                    row["description"],
                    row["status"],
                    row["work_type"],
                    row["start_date"],
                    row["end_date"],
                    row["geometry_type"],
                    row["geometry_json"],
                    row["source_payload_json"],
                    row["last_synced_at"],
                )
            )
            loaded += 1

        _cleanup_expired_source_rows(cur, today)
        serving_loaded = _rebuild_wior_serving_table(
            cur,
            synced_at,
            today,
            tram_corridor_rd,
            spoor_segment_index,
        )

        conn.commit()

        finished_at = datetime.now(timezone.utc).isoformat()
        cur.execute(
            """
            UPDATE wior_sync_runs
            SET finished_at = ?, status = ?, records_fetched = ?, records_loaded = ?
            WHERE id = ?
            """,
            (finished_at, "success", len(features), loaded, sync_run_id)
        )
        conn.commit()

        return {
            "ok": True,
            "records_fetched": len(features),
            "records_loaded": loaded,
            "serving_loaded": serving_loaded,
            "tram_buffer_meters": TRAM_BUFFER_METERS,
            "synced_at": synced_at,
        }

    except Exception as exc:
        try:
            conn.rollback()
        except Exception:
            pass

        finished_at = datetime.now(timezone.utc).isoformat()
        if sync_run_id is not None:
            cur = conn.cursor()
            cur.execute(
                """
                UPDATE wior_sync_runs
                SET finished_at = ?, status = ?, error_message = ?
                WHERE id = ?
                """,
                (finished_at, "failed", str(exc), sync_run_id)
            )
            conn.commit()

        raise

    finally:
        conn.close()
        _wior_refresh_lock.release()


def sync_wior_data() -> dict:
    return refresh_wior_safely()


def get_cached_wior_serving_features(limit: int = 500, mode: str = "active") -> list[dict]:
    conn = get_wior_db()
    try:
        where_sql = ""
        params: list[object] = []

        if mode == "active":
            where_sql = "WHERE is_active = 1"
        elif mode == "next7":
            where_sql = "WHERE is_upcoming_7d = 1"
        elif mode == "next30":
            where_sql = "WHERE is_upcoming_30d = 1"
        elif mode == "all":
            where_sql = ""
        else:
            mode = "active"
            where_sql = "WHERE is_active = 1"

        query = f"""
            SELECT
                wior_id, project_code, project_name, description, status,
                work_type, start_date, end_date, geometry_type,
                geometry_json, is_active, is_upcoming_7d, is_upcoming_30d,
                is_expired, is_near_tram, segment_ids_json, last_built_at
            FROM wior_features_serving
            {where_sql}
            LIMIT ?
        """
        params.append(limit)

        rows = conn.execute(query, params).fetchall()

        result = []
        for row in rows:
            result.append({
                "wior_id": row["wior_id"],
                "project_code": row["project_code"],
                "project_name": row["project_name"],
                "description": row["description"],
                "status": row["status"],
                "work_type": row["work_type"],
                "start_date": row["start_date"],
                "end_date": row["end_date"],
                "geometry_type": row["geometry_type"],
                "geometry": json.loads(row["geometry_json"]),
                "is_active": row["is_active"],
                "is_upcoming_7d": row["is_upcoming_7d"],
                "is_upcoming_30d": row["is_upcoming_30d"],
                "is_expired": row["is_expired"],
                "is_near_tram": row["is_near_tram"],
                "segment_ids": json.loads(row["segment_ids_json"]) if row["segment_ids_json"] else [],
                "last_built_at": row["last_built_at"],
            })
        return result
    finally:
        conn.close()


def get_cached_wior_features(limit: int = 500) -> list[dict]:
    return get_cached_wior_serving_features(limit=limit, mode="active")