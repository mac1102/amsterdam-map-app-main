from __future__ import annotations

import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
HALTES_DATA_JS = ROOT / "static" / "data" / "haltes_data.js"

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


def extract_js_json(path: Path, variable_name: str) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8")
    marker_index = text.find(variable_name)
    if marker_index < 0:
        raise ValueError(f"{path} does not define {variable_name}")
    equals_index = text.find("=", marker_index)
    if equals_index < 0:
        raise ValueError(f"{path} has no assignment for {variable_name}")
    value, _ = json.JSONDecoder().raw_decode(text[equals_index + 1 :].lstrip())
    if not isinstance(value, dict):
        raise ValueError(f"{variable_name} is not a JSON object")
    return value


def clean_line_select(value: Any, allowed_codes: set[str]) -> list[str]:
    if not value or value == "-":
        return []
    return [
        code
        for code in (part.strip() for part in str(value).split("|"))
        if code in allowed_codes
    ]


def main() -> int:
    collection = extract_js_json(HALTES_DATA_JS, "RAW_TRAMMETRO_PUNTEN_2026")
    raw_features = collection.get("features") or []
    tram_features = [
        feature
        for feature in raw_features
        if (feature.get("properties") or {}).get("Modaliteit") == "Tram"
    ]
    old_visible = []
    new_visible = []
    added_by_29 = []

    for feature in tram_features:
        props = feature.get("properties") or {}
        old_codes = clean_line_select(props.get("Lijn_select"), OLD_FRONTEND_TRAM_CODES)
        new_codes = clean_line_select(props.get("Lijn_select"), VALID_TRAM_CODES)
        if old_codes:
            old_visible.append(feature)
        if new_codes:
            new_visible.append(feature)
        if not old_codes and new_codes:
            added_by_29.append(feature)

    print(f"raw Modaliteit=Tram count: {len(tram_features)}")
    print(f"old frontend-visible count using codes up to 27: {len(old_visible)}")
    print(f"new frontend-visible count including line 29: {len(new_visible)}")
    print(f"records added by including line 29: {len(added_by_29)}")
    for feature in added_by_29:
        props = feature.get("properties") or {}
        print(
            "- "
            f"id={feature.get('id')} "
            f"name={props.get('Naam')} "
            f"Lijn={props.get('Lijn')} "
            f"Lijn_select={props.get('Lijn_select')}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
