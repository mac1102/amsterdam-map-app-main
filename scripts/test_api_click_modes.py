from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path
from typing import Any

os.environ.setdefault("SESSION_SECRET", "test-session-secret")

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from fastapi import HTTPException

import backend.main as main


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


async def call_click(payload: dict[str, Any]) -> tuple[int, dict[str, Any]]:
    try:
        response = await main.click(payload, object())
    except HTTPException as exc:
        return exc.status_code, {"detail": exc.detail}
    return response.status_code, json.loads(response.body.decode("utf-8"))


def known_pixel_payload() -> dict[str, float]:
    if main.feature_index.stations:
        station = main.feature_index.stations[0]
        return {"x": station.x, "y": station.y}
    if main.feature_index.segments:
        x, y = main.feature_index.segments[0].geometry[0]
        return {"x": x, "y": y}
    raise RuntimeError("feature_index has no stations or segments for pixel-mode testing")


def print_result(label: str, data: dict[str, Any]) -> None:
    feature = data.get("feature") or {}
    debug = data.get("debug") or {}
    print(
        f"{label}: "
        f"hit={data.get('hit')} "
        f"hit_type={data.get('hit_type')} "
        f"id={feature.get('segment_id') or feature.get('id')} "
        f"mode={debug.get('mode')} "
        f"reason={debug.get('reason')}"
    )


async def run_checks() -> None:
    original_require_user = main._require_user
    original_postgis_lookup = main.find_nearest_segment_postgis
    main._require_user = lambda request: {"email": "test@example.com", "is_admin": True}

    try:
        pixel = known_pixel_payload()

        status_code, old_data = await call_click(pixel)
        require(status_code == 200, f"old pixel mode failed: {status_code} {old_data}")
        require({"hit", "hit_type", "feature", "debug", "map_px", "timestamp"} <= set(old_data), "old response shape changed")
        require(old_data["map_px"] is not None, "old pixel mode should return map_px")
        print_result("old pixel mode", old_data)

        lnglat = {"lng": 4.898486, "lat": 52.378897, "radius_m": 30}
        status_code, postgis_data = await call_click(lnglat)
        require(status_code == 200, f"lng/lat mode failed: {status_code} {postgis_data}")
        require(postgis_data["hit"] is True, "lng/lat mode should find a nearby segment")
        require(postgis_data["hit_type"] == "segment", "lng/lat mode should return segment hit_type")
        require(postgis_data["debug"]["mode"] == "postgis_lnglat", "lng/lat mode should report postgis_lnglat")
        require(":" not in postgis_data["feature"]["segment_id"], "PostGIS mode returned a pixel-style segment ID")
        print_result("lng/lat mode", postgis_data)

        status_code, combined_data = await call_click({**pixel, **lnglat})
        require(status_code == 200, f"combined mode failed: {status_code} {combined_data}")
        require(combined_data["debug"]["mode"] == "postgis_lnglat", "combined mode should try PostGIS first")
        require(combined_data["map_px"] is None, "combined PostGIS success should not return map_px")
        print_result("combined postgis-first mode", combined_data)

        main.find_nearest_segment_postgis = lambda lng, lat, radius_m=30.0: None
        status_code, fallback_data = await call_click({**pixel, **lnglat})
        require(status_code == 200, f"fallback mode failed: {status_code} {fallback_data}")
        require(fallback_data["map_px"] is not None, "fallback should use old pixel mode when x/y exists")
        require((fallback_data.get("debug") or {}).get("mode") != "postgis_lnglat", "fallback should not report PostGIS success")
        print_result("combined fallback mode", fallback_data)
        main.find_nearest_segment_postgis = original_postgis_lookup

        status_code, _ = await call_click({"lng": 999, "lat": 52.0})
        require(status_code == 400, "invalid lng/lat should return 400")
        print(f"invalid lng/lat mode: status={status_code}")

        status_code, outside_data = await call_click({"lng": 5.5, "lat": 53.0, "radius_m": 30})
        require(status_code == 200, f"outside Amsterdam failed: {status_code} {outside_data}")
        require(outside_data["hit"] is False, "outside Amsterdam should return no hit")
        print_result("outside Amsterdam lng/lat mode", outside_data)
    finally:
        main._require_user = original_require_user
        main.find_nearest_segment_postgis = original_postgis_lookup


def main_script() -> int:
    asyncio.run(run_checks())
    return 0


if __name__ == "__main__":
    raise SystemExit(main_script())
