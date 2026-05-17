from __future__ import annotations

import argparse
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.postgis_queries import find_nearest_segment_postgis


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Test PostGIS nearest tram segment selection.")
    parser.add_argument("--lng", type=float, required=True, help="Longitude in EPSG:4326")
    parser.add_argument("--lat", type=float, required=True, help="Latitude in EPSG:4326")
    parser.add_argument("--radius-m", type=float, default=30.0, help="Search radius in meters")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    result = find_nearest_segment_postgis(args.lng, args.lat, args.radius_m)
    if result is None:
        print("No segment found.")
        return 0

    geometry = result.get("geometry") or {}
    print("Segment found.")
    print(f"segment_id: {result.get('segment_id')}")
    print(f"line_id: {result.get('line_id')}")
    print(f"line_name: {result.get('line_name')}")
    print(f"source: {result.get('source')}")
    print(f"bookable: {result.get('bookable')}")
    print(f"distance_m: {result.get('distance_m'):.3f}")
    print(f"geometry type: {geometry.get('type')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
