from __future__ import annotations

import json
import math
import os
from typing import Any


def get_database_url() -> str:
    return os.getenv("DATABASE_URL", "").strip()


def validate_lng_lat(lng: float, lat: float) -> None:
    if not math.isfinite(lng) or not math.isfinite(lat):
        raise ValueError("lng and lat must be finite numbers")
    if lng < -180 or lng > 180:
        raise ValueError("lng must be between -180 and 180")
    if lat < -90 or lat > 90:
        raise ValueError("lat must be between -90 and 90")


def validate_radius(radius_m: float) -> None:
    if not math.isfinite(radius_m):
        raise ValueError("radius_m must be a finite number")
    if radius_m <= 0:
        raise ValueError("radius_m must be greater than 0")


def is_postgis_click_available() -> bool:
    database_url = get_database_url()
    if not database_url:
        return False

    try:
        import psycopg
    except ImportError:
        return False

    try:
        with psycopg.connect(database_url, connect_timeout=3) as conn:
            row = conn.execute("SELECT to_regclass('public.tram_segments') IS NOT NULL").fetchone()
    except Exception:
        return False

    return bool(row and row[0])


def find_nearest_segment_postgis(
    lng: float,
    lat: float,
    radius_m: float = 30.0,
) -> dict[str, Any] | None:
    validate_lng_lat(lng, lat)
    validate_radius(radius_m)

    database_url = get_database_url()
    if not database_url:
        return None

    try:
        import psycopg
    except ImportError:
        return None

    sql = """
        SELECT
            segment_id,
            line_id,
            line_name,
            source,
            bookable,
            ST_Distance(
                geom::geography,
                ST_SetSRID(ST_MakePoint(%s, %s), 4326)::geography
            ) AS distance_m,
            ST_AsGeoJSON(geom)::json AS geometry
        FROM tram_segments
        WHERE ST_DWithin(
            geom::geography,
            ST_SetSRID(ST_MakePoint(%s, %s), 4326)::geography,
            %s
        )
        ORDER BY distance_m
        LIMIT 1
    """

    try:
        with psycopg.connect(database_url, connect_timeout=3) as conn:
            row = conn.execute(sql, (lng, lat, lng, lat, radius_m)).fetchone()
    except Exception:
        return None

    if row is None:
        return None

    geometry = row[6]
    if isinstance(geometry, str):
        geometry = json.loads(geometry)

    return {
        "segment_id": row[0],
        "line_id": row[1],
        "line_name": row[2],
        "source": row[3],
        "bookable": bool(row[4]),
        "distance_m": float(row[5]),
        "geometry": geometry,
    }
