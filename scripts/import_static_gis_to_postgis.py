from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import psycopg


ROOT = Path(__file__).resolve().parents[1]
SPOOR_DATA_JS = ROOT / "static" / "data" / "spoor_data.js"
SPOOR_SEGMENTS_GEOJSON = ROOT / "backend" / "data" / "spoor_segments.geojson"
HALTES_DATA_JS = ROOT / "static" / "data" / "haltes_data.js"
DERIVED_GAP_CANDIDATES = (
    ROOT / "derived_rail_gap_segments.geojson",
    ROOT / "backend" / "data" / "derived_rail_gap_segments.geojson",
    ROOT / "static" / "data" / "derived_rail_gap_segments.geojson",
)

PIXEL_FEATURE_ID_RE = re.compile(r"^[A-Za-z]:\d+:\d+(?::\d+)+$")
SKIPPED_SEGMENTS: list[tuple[str, str]] = []
OLD_FRONTEND_TRAM_CODES = {
    "01",
    "02",
    "04",
    "05",
    "06",
    "07",
    "12",
    "13",
    "14",
    "17",
    "19",
    "24",
    "25",
    "26",
    "27",
}
VALID_TRAM_CODES = OLD_FRONTEND_TRAM_CODES | {"29"}


@dataclass(frozen=True)
class SegmentRecord:
    segment_id: str
    line_id: str | None
    line_name: str | None
    color: str | None
    source: str
    bookable: bool
    geometry: dict[str, Any]


@dataclass(frozen=True)
class StopRecord:
    stop_id: str
    stop_name: str | None
    stop_type: str | None
    source: str
    raw_modaliteit: str | None
    raw_lijn: str | None
    raw_lijn_select: str | None
    current_display_lijn: str | None
    current_display_lijn_select: str | None
    valid_tram_lijn: str | None
    valid_tram_lijn_select: str | None
    is_current_frontend_visible: bool
    is_valid_tram_line_stop: bool
    geometry: dict[str, Any]


def repo_path(path: Path) -> str:
    try:
        return str(path.relative_to(ROOT)).replace("\\", "/")
    except ValueError:
        return str(path)


def load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        value = json.load(handle)
    if not isinstance(value, dict):
        raise ValueError(f"{repo_path(path)} did not contain a JSON object")
    return value


def extract_js_json(path: Path, variable_name: str) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8")
    marker = variable_name
    marker_index = text.find(marker)
    if marker_index < 0:
        raise ValueError(f"{repo_path(path)} does not define {variable_name}")

    equals_index = text.find("=", marker_index)
    if equals_index < 0:
        raise ValueError(f"{repo_path(path)} has no assignment for {variable_name}")

    payload = text[equals_index + 1 :].lstrip()
    decoder = json.JSONDecoder()
    value, _ = decoder.raw_decode(payload)
    if not isinstance(value, dict):
        raise ValueError(f"{variable_name} in {repo_path(path)} was not a JSON object")
    return value


def features(collection: dict[str, Any], label: str) -> list[dict[str, Any]]:
    raw_features = collection.get("features")
    if not isinstance(raw_features, list):
        raise ValueError(f"{label} does not have a FeatureCollection features array")
    return [feature for feature in raw_features if isinstance(feature, dict)]


def text_value(*values: Any) -> str | None:
    for value in values:
        if value is None:
            continue
        text = str(value).strip()
        if text:
            return text
    return None


def clean_line_select(value: Any, allowed_codes: set[str]) -> list[str]:
    text = text_value(value)
    if not text or text == "-":
        return []
    return [code for code in (part.strip() for part in text.split("|")) if code in allowed_codes]


def format_line_text(codes: list[str]) -> str | None:
    if not codes:
        return None
    return " | ".join(str(int(code)) for code in codes)


def is_position(value: Any) -> bool:
    return (
        isinstance(value, list)
        and len(value) >= 2
        and isinstance(value[0], (int, float))
        and isinstance(value[1], (int, float))
    )


def walk_positions(coordinates: Any) -> list[tuple[float, float]]:
    if is_position(coordinates):
        return [(float(coordinates[0]), float(coordinates[1]))]
    if isinstance(coordinates, list):
        positions: list[tuple[float, float]] = []
        for item in coordinates:
            positions.extend(walk_positions(item))
        return positions
    return []


def geometry_positions(geometry: dict[str, Any]) -> list[tuple[float, float]]:
    return walk_positions(geometry.get("coordinates"))


def validate_wgs84_geometry(geometry: dict[str, Any], label: str) -> None:
    positions = geometry_positions(geometry)
    if not positions:
        raise ValueError(f"{label} has no coordinate positions")

    xs = [position[0] for position in positions]
    ys = [position[1] for position in positions]
    min_x, max_x = min(xs), max(xs)
    min_y, max_y = min(ys), max(ys)

    if min_x < -180 or max_x > 180 or min_y < -90 or max_y > 90:
        raise ValueError(
            f"{label} coordinates look projected instead of EPSG:4326: "
            f"bbox=({min_x}, {min_y}, {max_x}, {max_y})"
        )

    if max_x < 3 or min_x > 8 or max_y < 50 or min_y > 55:
        print(
            f"warning: {label} bbox is valid WGS84 but outside the expected Netherlands range: "
            f"({min_x}, {min_y}, {max_x}, {max_y})"
        )


def has_two_distinct_points(line_coordinates: Any) -> bool:
    positions = geometry_positions({"coordinates": line_coordinates})
    distinct = {(round(lon, 12), round(lat, 12)) for lon, lat in positions}
    return len(distinct) >= 2


def has_valid_line_components(geometry: dict[str, Any]) -> bool:
    geometry_type = geometry.get("type")
    coordinates = geometry.get("coordinates")
    if geometry_type == "LineString":
        return has_two_distinct_points(coordinates)
    if geometry_type == "MultiLineString" and isinstance(coordinates, list):
        return bool(coordinates) and all(has_two_distinct_points(line) for line in coordinates)
    return False


def collection_id_set(collection: dict[str, Any], property_name: str) -> set[str]:
    ids: set[str] = set()
    for feature in features(collection, property_name):
        props = feature.get("properties") or {}
        if not isinstance(props, dict):
            continue
        value = text_value(props.get(property_name))
        if value:
            ids.add(value)
    return ids


def load_segment_collection() -> tuple[str, dict[str, Any]]:
    spoor_data = extract_js_json(SPOOR_DATA_JS, "SPOOR_DATA")
    spoor_data_ids = collection_id_set(spoor_data, "k")

    if SPOOR_SEGMENTS_GEOJSON.exists():
        derived = load_json(SPOOR_SEGMENTS_GEOJSON)
        derived_ids = collection_id_set(derived, "segment_id")
        missing = spoor_data_ids - derived_ids
        extra = derived_ids - spoor_data_ids
        if spoor_data_ids and not missing and not extra:
            print(
                f"Using {repo_path(SPOOR_SEGMENTS_GEOJSON)} for tram_segments "
                f"({len(derived_ids)} stable segment IDs)."
            )
            return repo_path(SPOOR_SEGMENTS_GEOJSON), derived

        print(
            f"Preferred source {repo_path(SPOOR_SEGMENTS_GEOJSON)} has "
            f"{len(derived_ids)} IDs; {repo_path(SPOOR_DATA_JS)} has {len(spoor_data_ids)} IDs. "
            f"Falling back to {repo_path(SPOOR_DATA_JS)} to keep the KGE/static segment ID set complete."
        )
    else:
        print(f"Preferred source {repo_path(SPOOR_SEGMENTS_GEOJSON)} not found.")

    print(f"Using {repo_path(SPOOR_DATA_JS)} for tram_segments.")
    return repo_path(SPOOR_DATA_JS), spoor_data


def segment_record_from_feature(
    feature: dict[str, Any],
    source: str,
    bookable: bool,
    label: str,
) -> SegmentRecord | None:
    props = feature.get("properties") or {}
    if not isinstance(props, dict):
        props = {}

    segment_id = text_value(props.get("segment_id"), props.get("k"))
    if not segment_id:
        print(f"warning: skipping {label}; missing segment_id/properties.k")
        return None

    if PIXEL_FEATURE_ID_RE.match(segment_id):
        raise ValueError(
            f"{label} has a features.json-style pixel ID ({segment_id}); "
            "static KGE IDs are required"
        )

    geometry = feature.get("geometry")
    if not isinstance(geometry, dict):
        print(f"warning: skipping segment {segment_id}; missing geometry")
        return None

    geometry_type = geometry.get("type")
    if geometry_type not in {"LineString", "MultiLineString"}:
        print(f"warning: skipping segment {segment_id}; unsupported geometry type {geometry_type}")
        return None

    validate_wgs84_geometry(geometry, f"segment {segment_id}")
    if not has_valid_line_components(geometry):
        SKIPPED_SEGMENTS.append((segment_id, source))
        return None

    line_id = text_value(props.get("line_id"), props.get("li"), props.get("line"))
    line_name = text_value(props.get("line_name"), props.get("route_name"))
    color = text_value(props.get("raw_color"), props.get("color"), props.get("c"))
    return SegmentRecord(
        segment_id=segment_id,
        line_id=line_id,
        line_name=line_name,
        color=color,
        source=source,
        bookable=bookable,
        geometry=geometry,
    )


def load_segment_records() -> tuple[str, list[SegmentRecord]]:
    source_name, collection = load_segment_collection()
    records: list[SegmentRecord] = []
    seen: set[str] = set()
    skipped_before = len(SKIPPED_SEGMENTS)
    for index, feature in enumerate(features(collection, source_name), start=1):
        record = segment_record_from_feature(
            feature,
            source="official_kge",
            bookable=True,
            label=f"{source_name} feature {index}",
        )
        if record is None:
            continue
        if record.segment_id in seen:
            print(f"warning: duplicate segment_id {record.segment_id}; keeping last value")
        seen.add(record.segment_id)
        records.append(record)
    skipped = SKIPPED_SEGMENTS[skipped_before:]
    if skipped:
        sample = ", ".join(segment_id for segment_id, _ in skipped[:8])
        print(
            f"Skipped {len(skipped)} tram_segments with fewer than two distinct points; "
            f"sample IDs: {sample}"
        )
    return source_name, records


def find_derived_gap_file() -> Path | None:
    for path in DERIVED_GAP_CANDIDATES:
        if path.exists():
            return path
    return None


def stable_gap_id(feature: dict[str, Any]) -> str:
    props = feature.get("properties") or {}
    if isinstance(props, dict):
        existing = text_value(props.get("segment_id"), props.get("k"), props.get("id"))
        if existing:
            return existing
    geometry = feature.get("geometry") or {}
    digest = hashlib.sha1(json.dumps(geometry, sort_keys=True).encode("utf-8")).hexdigest()
    return f"derived_gap:{digest[:16]}"


def load_gap_records() -> tuple[str | None, list[SegmentRecord]]:
    path = find_derived_gap_file()
    if path is None:
        print("derived rail gap file not found; skipping.")
        return None, []

    collection = load_json(path)
    records: list[SegmentRecord] = []
    skipped_before = len(SKIPPED_SEGMENTS)
    for index, feature in enumerate(features(collection, repo_path(path)), start=1):
        props = feature.get("properties") or {}
        if not isinstance(props, dict):
            props = {}
        props = dict(props)
        props.setdefault("segment_id", stable_gap_id(feature))
        copied_feature = dict(feature)
        copied_feature["properties"] = props
        record = segment_record_from_feature(
            copied_feature,
            source="derived_gap",
            bookable=False,
            label=f"{repo_path(path)} feature {index}",
        )
        if record is not None:
            records.append(record)
    skipped = SKIPPED_SEGMENTS[skipped_before:]
    if skipped:
        sample = ", ".join(segment_id for segment_id, _ in skipped[:8])
        print(
            f"Skipped {len(skipped)} derived gap tram_segments with fewer than two distinct points; "
            f"sample IDs: {sample}"
        )
    print(f"Using {repo_path(path)} for derived gap segments ({len(records)} records).")
    return repo_path(path), records


def load_stop_records() -> list[StopRecord]:
    collection = extract_js_json(HALTES_DATA_JS, "RAW_TRAMMETRO_PUNTEN_2026")
    raw_features = features(collection, repo_path(HALTES_DATA_JS))
    stop_features: list[dict[str, Any]] = []

    for feature in raw_features:
        props = feature.get("properties") or {}
        if not isinstance(props, dict):
            continue
        modality = text_value(props.get("Modaliteit"), props.get("mode"))
        if modality and modality.lower() == "tram":
            stop_features.append(feature)

    if not stop_features:
        raise RuntimeError(f"{repo_path(HALTES_DATA_JS)} yielded no raw Modaliteit=Tram stops")

    records: list[StopRecord] = []
    seen: set[str] = set()
    for index, feature in enumerate(stop_features, start=1):
        props = feature.get("properties") or {}
        if not isinstance(props, dict):
            props = {}
        geometry = feature.get("geometry")
        if not isinstance(geometry, dict):
            print(f"warning: skipping stop feature {index}; missing geometry")
            continue
        if geometry.get("type") != "Point":
            print(f"warning: skipping stop feature {index}; unsupported geometry type {geometry.get('type')}")
            continue
        validate_wgs84_geometry(geometry, f"stop feature {index}")

        coordinates = geometry.get("coordinates")
        lon, lat = float(coordinates[0]), float(coordinates[1])
        stop_name = text_value(props.get("stop_name"), props.get("Naam"), props.get("name"), props.get("Label"))
        stop_id = text_value(props.get("stop_id"), props.get("halte_id"), props.get("id"), feature.get("id"))
        if not stop_id:
            digest_input = f"{stop_name or ''}|{lon:.7f}|{lat:.7f}"
            digest = hashlib.sha1(digest_input.encode("utf-8")).hexdigest()
            stop_id = f"stop:{digest[:16]}"

        if stop_id in seen:
            print(f"warning: duplicate stop_id {stop_id}; keeping last value")
        seen.add(stop_id)

        stop_type = text_value(props.get("stop_type"), props.get("type"))
        if not stop_type:
            modality = text_value(props.get("Modaliteit"), props.get("mode"))
            if modality and modality.lower() == "tram":
                stop_type = "tram_stop"
            elif modality:
                stop_type = modality.lower()

        raw_modaliteit = text_value(props.get("Modaliteit"), props.get("mode"))
        raw_lijn = text_value(props.get("Lijn"))
        raw_lijn_select = text_value(props.get("Lijn_select"))
        current_codes = clean_line_select(raw_lijn_select, OLD_FRONTEND_TRAM_CODES)
        valid_codes = clean_line_select(raw_lijn_select, VALID_TRAM_CODES)
        current_display_lijn_select = "|".join(current_codes) if current_codes else None
        valid_tram_lijn_select = "|".join(valid_codes) if valid_codes else None

        records.append(
            StopRecord(
                stop_id=stop_id,
                stop_name=stop_name,
                stop_type=stop_type,
                source="official_kge",
                raw_modaliteit=raw_modaliteit,
                raw_lijn=raw_lijn,
                raw_lijn_select=raw_lijn_select,
                current_display_lijn=format_line_text(current_codes),
                current_display_lijn_select=current_display_lijn_select,
                valid_tram_lijn=format_line_text(valid_codes),
                valid_tram_lijn_select=valid_tram_lijn_select,
                is_current_frontend_visible=bool(current_codes),
                is_valid_tram_line_stop=bool(valid_codes),
                geometry=geometry,
            )
        )

    current_visible = sum(1 for record in records if record.is_current_frontend_visible)
    valid_visible = sum(1 for record in records if record.is_valid_tram_line_stop)
    print(
        f"Using {repo_path(HALTES_DATA_JS)} for raw Modaliteit=Tram tram_stops "
        f"({len(records)} records; old visible {current_visible}, valid tram-line {valid_visible})."
    )
    return records


def connect() -> psycopg.Connection[Any]:
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        raise RuntimeError("DATABASE_URL is not set")
    return psycopg.connect(database_url)


def line_rows(segment_records: list[SegmentRecord]) -> list[tuple[str, str | None, str | None, str]]:
    rows_by_id: dict[str, tuple[str, str | None, str | None, str]] = {}
    for record in segment_records:
        if not record.line_id:
            continue
        existing = rows_by_id.get(record.line_id)
        line_name = record.line_name or (existing[1] if existing else None)
        color = record.color or (existing[2] if existing else None)
        rows_by_id[record.line_id] = (record.line_id, line_name, color, record.source)
    return list(rows_by_id.values())


def upsert_lines(conn: psycopg.Connection[Any], rows: list[tuple[str, str | None, str | None, str]]) -> None:
    sql = """
        INSERT INTO tram_lines (line_id, line_name, mode, color, source, updated_at)
        VALUES (%s, %s, 'tram', %s, %s, now())
        ON CONFLICT (line_id)
        DO UPDATE SET
            line_name = COALESCE(EXCLUDED.line_name, tram_lines.line_name),
            color = COALESCE(EXCLUDED.color, tram_lines.color),
            source = EXCLUDED.source,
            updated_at = now()
    """
    for row in rows:
        conn.execute(sql, row)


def delete_skipped_segments(conn: psycopg.Connection[Any]) -> None:
    if not SKIPPED_SEGMENTS:
        return

    deleted = 0
    retained = 0
    sql = """
        DELETE FROM tram_segments AS segment
        WHERE segment.segment_id = %s
            AND segment.source = %s
            AND NOT EXISTS (
                SELECT 1
                FROM application_targets AS target
                WHERE target.segment_id = segment.segment_id
            )
    """
    for segment_id, source in SKIPPED_SEGMENTS:
        cursor = conn.execute(sql, (segment_id, source))
        deleted += cursor.rowcount or 0
        if not cursor.rowcount:
            exists = scalar(
                conn,
                "SELECT EXISTS (SELECT 1 FROM tram_segments WHERE segment_id = %s AND source = %s)",
                (segment_id, source),
            )
            retained += 1 if exists else 0

    print(f"Removed {deleted} previously imported invalid/skipped tram_segments.")
    if retained:
        print(
            f"warning: retained {retained} skipped tram_segments because they are referenced by application_targets"
        )


def upsert_segments(conn: psycopg.Connection[Any], records: list[SegmentRecord]) -> None:
    sql = """
        INSERT INTO tram_segments (
            segment_id,
            line_id,
            line_name,
            source,
            bookable,
            geom,
            updated_at
        )
        VALUES (
            %s,
            %s,
            %s,
            %s,
            %s,
            ST_Multi(ST_SetSRID(ST_GeomFromGeoJSON(%s), 4326))::geometry(MultiLineString, 4326),
            now()
        )
        ON CONFLICT (segment_id)
        DO UPDATE SET
            line_id = EXCLUDED.line_id,
            line_name = EXCLUDED.line_name,
            source = EXCLUDED.source,
            bookable = EXCLUDED.bookable,
            geom = EXCLUDED.geom,
            updated_at = now()
    """
    for record in records:
        conn.execute(
            sql,
            (
                record.segment_id,
                record.line_id,
                record.line_name,
                record.source,
                record.bookable,
                json.dumps(record.geometry, separators=(",", ":")),
            ),
        )


def upsert_stops(conn: psycopg.Connection[Any], records: list[StopRecord]) -> None:
    sql = """
        INSERT INTO tram_stops (
            stop_id,
            stop_name,
            stop_type,
            source,
            raw_modaliteit,
            raw_lijn,
            raw_lijn_select,
            current_display_lijn,
            current_display_lijn_select,
            valid_tram_lijn,
            valid_tram_lijn_select,
            is_current_frontend_visible,
            is_valid_tram_line_stop,
            geom,
            updated_at
        )
        VALUES (
            %s,
            %s,
            %s,
            %s,
            %s,
            %s,
            %s,
            %s,
            %s,
            %s,
            %s,
            %s,
            %s,
            ST_SetSRID(ST_GeomFromGeoJSON(%s), 4326)::geometry(Point, 4326),
            now()
        )
        ON CONFLICT (stop_id)
        DO UPDATE SET
            stop_name = EXCLUDED.stop_name,
            stop_type = EXCLUDED.stop_type,
            source = EXCLUDED.source,
            raw_modaliteit = EXCLUDED.raw_modaliteit,
            raw_lijn = EXCLUDED.raw_lijn,
            raw_lijn_select = EXCLUDED.raw_lijn_select,
            current_display_lijn = EXCLUDED.current_display_lijn,
            current_display_lijn_select = EXCLUDED.current_display_lijn_select,
            valid_tram_lijn = EXCLUDED.valid_tram_lijn,
            valid_tram_lijn_select = EXCLUDED.valid_tram_lijn_select,
            is_current_frontend_visible = EXCLUDED.is_current_frontend_visible,
            is_valid_tram_line_stop = EXCLUDED.is_valid_tram_line_stop,
            geom = EXCLUDED.geom,
            updated_at = now()
    """
    for record in records:
        conn.execute(
            sql,
            (
                record.stop_id,
                record.stop_name,
                record.stop_type,
                record.source,
                record.raw_modaliteit,
                record.raw_lijn,
                record.raw_lijn_select,
                record.current_display_lijn,
                record.current_display_lijn_select,
                record.valid_tram_lijn,
                record.valid_tram_lijn_select,
                record.is_current_frontend_visible,
                record.is_valid_tram_line_stop,
                json.dumps(record.geometry, separators=(",", ":")),
            ),
        )


def scalar(conn: psycopg.Connection[Any], sql: str, params: tuple[Any, ...] = ()) -> Any:
    row = conn.execute(sql, params).fetchone()
    if row is None:
        return None
    return row[0]


def values(conn: psycopg.Connection[Any], sql: str) -> list[Any]:
    return [row[0] for row in conn.execute(sql).fetchall()]


def print_validation(conn: psycopg.Connection[Any]) -> None:
    print("\nPostGIS import validation:")
    print(f"tram_lines count: {scalar(conn, 'SELECT COUNT(*) FROM tram_lines')}")
    print(f"tram_segments count: {scalar(conn, 'SELECT COUNT(*) FROM tram_segments')}")
    print(f"tram_stops count: {scalar(conn, 'SELECT COUNT(*) FROM tram_stops')}")
    print(
        "invalid tram_segments geometries: "
        f"{scalar(conn, 'SELECT COUNT(*) FROM tram_segments WHERE NOT ST_IsValid(geom)')}"
    )
    print(
        "invalid tram_stops geometries: "
        f"{scalar(conn, 'SELECT COUNT(*) FROM tram_stops WHERE NOT ST_IsValid(geom)')}"
    )
    pixel_like_count = scalar(
        conn,
        "SELECT COUNT(*) FROM tram_segments WHERE segment_id ~ '^[A-Za-z]:[0-9]+:[0-9]+(:[0-9]+)+$'",
    )
    print(f"features.json pixel-like segment IDs: {pixel_like_count}")

    sample_segment_ids = values(
        conn,
        "SELECT segment_id FROM tram_segments ORDER BY segment_id LIMIT 8",
    )
    sample_stop_ids = values(
        conn,
        "SELECT stop_id FROM tram_stops ORDER BY stop_id LIMIT 8",
    )
    print("sample segment_id values: " + ", ".join(sample_segment_ids))
    print("sample stop_id values: " + ", ".join(sample_stop_ids))
    print(
        "old frontend-visible tram stops: "
        f"{scalar(conn, 'SELECT COUNT(*) FROM tram_stops WHERE is_current_frontend_visible')}"
    )
    print(
        "valid tram-line stops including line 29: "
        f"{scalar(conn, 'SELECT COUNT(*) FROM tram_stops WHERE is_valid_tram_line_stop')}"
    )


def run_import() -> None:
    segment_source, official_segments = load_segment_records()
    _, gap_segments = load_gap_records()
    stop_records = load_stop_records()

    segment_records = official_segments + gap_segments
    if not segment_records:
        raise RuntimeError("No tram segment records were found to import")
    if not stop_records:
        raise RuntimeError("No tram stop records were found to import")

    with connect() as conn:
        with conn.transaction():
            delete_skipped_segments(conn)
            upsert_lines(conn, line_rows(segment_records))
            upsert_segments(conn, segment_records)
            upsert_stops(conn, stop_records)
            print(
                f"\nUpserted {len(line_rows(segment_records))} tram_lines derived from "
                f"{len(segment_records)} tram_segments."
            )
            print(f"Upserted {len(official_segments)} official tram_segments from {segment_source}.")
            if gap_segments:
                print(f"Upserted {len(gap_segments)} derived gap tram_segments.")
            print(f"Upserted {len(stop_records)} tram_stops.")
            print_validation(conn)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Import static Amsterdam tram GIS data into PostgreSQL/PostGIS."
    )
    return parser.parse_args()


def main() -> int:
    parse_args()
    try:
        run_import()
    except Exception as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
