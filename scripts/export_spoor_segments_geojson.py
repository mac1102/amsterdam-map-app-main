from __future__ import annotations

import json
import re
from pathlib import Path

from pyproj import Transformer
from shapely.geometry import shape
from shapely.ops import transform

ROOT = Path(__file__).resolve().parents[1]

SPOOR_SOURCE_PATH = ROOT / "static" / "data" / "spoor_data.js"
BOVENLEIDING_SOURCE_PATH = ROOT / "static" / "data" / "bovenleiding_data.js"
OUTPUT_PATH = ROOT / "backend" / "data" / "spoor_segments.geojson"

# Both frontend files appear to be WGS84 already
WGS84_TO_RD = Transformer.from_crs("EPSG:4326", "EPSG:28992", always_xy=True)

# Small metric tolerance so line-on-line checks are not too brittle
OVERHEAD_MATCH_BUFFER_METERS = 2.0


def extract_geojson_from_js(js_text: str) -> dict:
    text = js_text.strip()

    # Remove leading const/let/var wrapper
    text = re.sub(r"^\s*(const|let|var)\s+[A-Za-z0-9_]+\s*=\s*", "", text, count=1)

    # Remove trailing semicolon if present
    text = text.strip()
    if text.endswith(";"):
        text = text[:-1].strip()

    return json.loads(text)


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


def load_spoor_data() -> dict:
    raw = SPOOR_SOURCE_PATH.read_text(encoding="utf-8", errors="replace")
    return extract_geojson_from_js(raw)


def load_bovenleiding_data() -> dict:
    raw = BOVENLEIDING_SOURCE_PATH.read_text(encoding="utf-8", errors="replace")
    return extract_geojson_from_js(raw)


def build_overhead_index(bovenleiding_data: dict) -> list[dict]:
    features = bovenleiding_data.get("features", []) or []
    indexed = []

    for feature in features:
        props = feature.get("properties", {}) or {}
        geometry = feature.get("geometry") or {}
        geom = safe_shape(geometry)
        if geom is None:
            continue

        geom_rd = transform(WGS84_TO_RD.transform, geom)
        if not geom_rd.is_valid:
            geom_rd = geom_rd.buffer(0)

        if geom_rd.is_empty:
            continue

        indexed.append(
            {
                "id": props.get("id"),
                "group_code": props.get("s"),
                "drawing_ref": props.get("t"),
                "color": props.get("c"),
                "geom_rd": geom_rd.buffer(OVERHEAD_MATCH_BUFFER_METERS),
            }
        )

    return indexed


def get_line_name(props: dict) -> str | None:
    # Prefer the more human label first
    return props.get("s") or props.get("z") or props.get("li") or None


def match_overhead(segment_geom_rd, overhead_index: list[dict]) -> dict:
    overhead_ids = []
    overhead_group_codes = []

    for item in overhead_index:
        try:
            if segment_geom_rd.intersects(item["geom_rd"]):
                if item["id"] is not None:
                    overhead_ids.append(str(item["id"]))
                if item["group_code"] is not None:
                    overhead_group_codes.append(str(item["group_code"]))
        except Exception:
            continue

    overhead_ids = sorted(set(overhead_ids))
    overhead_group_codes = sorted(set(overhead_group_codes))

    return {
        "has_overhead_match": len(overhead_ids) > 0,
        "overhead_ids": overhead_ids,
        "overhead_group_codes": overhead_group_codes,
    }


def main() -> None:
    spoor_data = load_spoor_data()
    bovenleiding_data = load_bovenleiding_data()
    overhead_index = build_overhead_index(bovenleiding_data)

    spoor_features = spoor_data.get("features", []) or []

    out_features = []
    kept = 0
    skipped = 0
    matched_overhead = 0

    for feature in spoor_features:
        props = feature.get("properties", {}) or {}
        geometry = feature.get("geometry") or {}

        geom_type = geometry.get("type")
        if geom_type not in {"LineString", "MultiLineString"}:
            skipped += 1
            continue

        segment_id = props.get("k")
        if not segment_id:
            skipped += 1
            continue

        geom = safe_shape(geometry)
        if geom is None:
            skipped += 1
            continue

        geom_rd = transform(WGS84_TO_RD.transform, geom)
        if not geom_rd.is_valid:
            geom_rd = geom_rd.buffer(0)

        if geom_rd.is_empty:
            skipped += 1
            continue

        overhead_match = match_overhead(geom_rd, overhead_index)
        if overhead_match["has_overhead_match"]:
            matched_overhead += 1

        out_features.append(
            {
                "type": "Feature",
                "properties": {
                    "segment_id": str(segment_id),
                    "line_id": props.get("li"),
                    "line_name": get_line_name(props),
                    "segment_type": props.get("t"),
                    "route_code": props.get("r"),
                    "surface_type": props.get("v"),
                    "year": props.get("j"),
                    "raw_color": props.get("c"),
                    "has_overhead_match": overhead_match["has_overhead_match"],
                    "overhead_ids": overhead_match["overhead_ids"],
                    "overhead_group_codes": overhead_match["overhead_group_codes"],
                },
                "geometry": geometry,
            }
        )
        kept += 1

    out = {
        "type": "FeatureCollection",
        "features": out_features,
    }

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(
        json.dumps(out, ensure_ascii=False),
        encoding="utf-8",
    )

    print(f"Wrote {kept} spoor segment features to {OUTPUT_PATH}")
    print(f"Skipped {skipped} source features")
    print(f"Segments with overhead match: {matched_overhead}")
    print(f"Overhead sections indexed: {len(overhead_index)}")


if __name__ == "__main__":
    main()