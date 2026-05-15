from pathlib import Path
import json
import re

ROOT = Path(__file__).resolve().parents[1]
SOURCE_PATH = ROOT / "static" / "data" / "spoor_data.js"
OUTPUT_PATH = ROOT / "backend" / "data" / "tram_tracks.geojson"


def extract_geojson_from_js(js_text: str) -> dict:
    text = js_text.strip()

    # Remove leading "const X =" / "let X =" / "var X ="
    text = re.sub(r"^\s*(const|let|var)\s+[A-Za-z0-9_]+\s*=\s*", "", text, count=1)

    # Remove trailing semicolon if present
    text = text.strip()
    if text.endswith(";"):
        text = text[:-1].strip()

    return json.loads(text)


def main():
    raw = SOURCE_PATH.read_text(encoding="utf-8", errors="replace")
    data = extract_geojson_from_js(raw)

    features = data.get("features", []) or []

    line_features = []
    for feature in features:
        geometry = (feature or {}).get("geometry") or {}
        geom_type = geometry.get("type")
        if geom_type in {"LineString", "MultiLineString"}:
            line_features.append({
                "type": "Feature",
                "properties": {},
                "geometry": geometry,
            })

    if not line_features:
        raise RuntimeError("No LineString/MultiLineString features found in source data.")

    out = {
        "type": "FeatureCollection",
        "features": line_features,
    }

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(
        json.dumps(out, ensure_ascii=False),
        encoding="utf-8"
    )

    print(f"Wrote {len(line_features)} line features to {OUTPUT_PATH}")


if __name__ == "__main__":
    main()