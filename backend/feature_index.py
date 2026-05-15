from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


@dataclass(frozen=True)
class Station:
    id: str
    name: str
    x: float
    y: float
    lines: List[str]


@dataclass(frozen=True)
class Segment:
    id: str
    line_id: str
    name: str
    geometry: List[Tuple[float, float]]


def _point_to_segment_distance(px: float, py: float, ax: float, ay: float, bx: float, by: float) -> float:
    abx, aby = bx - ax, by - ay
    apx, apy = px - ax, py - ay
    ab2 = abx * abx + aby * aby
    if ab2 == 0:
        return math.hypot(px - ax, py - ay)
    t = (apx * abx + apy * aby) / ab2
    t = max(0.0, min(1.0, t))
    cx, cy = ax + t * abx, ay + t * aby
    return math.hypot(px - cx, py - cy)


def _point_to_polyline_distance(px: float, py: float, geom: List[Tuple[float, float]]) -> float:
    best = float("inf")
    for i in range(len(geom) - 1):
        ax, ay = geom[i]
        bx, by = geom[i + 1]
        best = min(best, _point_to_segment_distance(px, py, ax, ay, bx, by))
    return best


class _GridIndex:
    def __init__(self, cell_size_px: float = 96.0):
        self.cell = float(cell_size_px)
        self.cells: Dict[Tuple[int, int], List[int]] = {}

    def _k(self, x: float, y: float) -> Tuple[int, int]:
        return (int(x // self.cell), int(y // self.cell))

    def insert_bbox(self, idx: int, bbox: Tuple[float, float, float, float]) -> None:
        x0, y0, x1, y1 = bbox
        ix0, iy0 = self._k(x0, y0)
        ix1, iy1 = self._k(x1, y1)
        for ix in range(ix0, ix1 + 1):
            for iy in range(iy0, iy1 + 1):
                self.cells.setdefault((ix, iy), []).append(idx)

    def query(self, x: float, y: float) -> List[int]:
        ix, iy = self._k(x, y)
        # search a small neighborhood
        out: List[int] = []
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                out.extend(self.cells.get((ix + dx, iy + dy), []))
        return out


class FeatureIndex:
    def __init__(self, features_path: Path, grid_cell_px: float = 96.0):
        raw = json.loads(Path(features_path).read_text(encoding="utf-8"))

        self.image = raw["image"]
        self.lines = {l["line_id"]: l for l in raw.get("lines", [])}

        self.stations: List[Station] = []
        for s in raw.get("stations", []):
            self.stations.append(
                Station(
                    id=s["id"],
                    name=s["name"],
                    x=float(s["x"]),
                    y=float(s["y"]),
                    lines=list(s.get("lines", [])),
                )
            )

        self.segments: List[Segment] = []
        for seg in raw.get("segments", []):
            geom = [(float(x), float(y)) for x, y in seg["geometry"]]
            self.segments.append(
                Segment(
                    id=seg["id"],
                    line_id=seg["line_id"],
                    name=seg.get("name", seg["id"]),
                    geometry=geom,
                )
            )

        self.raw = raw

        # Build spatial indices
        self._station_grid = _GridIndex(cell_size_px=grid_cell_px)
        for i, s in enumerate(self.stations):
            self._station_grid.insert_bbox(i, (s.x, s.y, s.x, s.y))

        self._segment_grid = _GridIndex(cell_size_px=grid_cell_px)
        self._segment_bbox: List[Tuple[float, float, float, float]] = []
        for i, seg in enumerate(self.segments):
            xs = [p[0] for p in seg.geometry]
            ys = [p[1] for p in seg.geometry]
            bbox = (min(xs), min(ys), max(xs), max(ys))
            self._segment_bbox.append(bbox)
            self._segment_grid.insert_bbox(i, bbox)

    def hit_test(self, x: float, y: float, station_radius_px: float = 18.0, seg_radius_px: float = 12.0) -> Dict[str, Any]:
        # Stations first (fast)
        best_station = None
        best_station_d = float("inf")
        candidates = self._station_grid.query(x, y)

        for idx in candidates:
            s = self.stations[idx]
            d = math.hypot(x - s.x, y - s.y)
            if d < best_station_d:
                best_station, best_station_d = s, d

        if best_station and best_station_d <= station_radius_px:
            return {
                "hit": True,
                "hit_type": "station",
                "feature": {
                    "id": best_station.id,
                    "name": best_station.name,
                    "lines": best_station.lines,
                    "mode": sorted({self.lines.get(l, {}).get("mode", "unknown") for l in best_station.lines}),
                },
                "debug": {"nearest_distance_px": best_station_d, "candidate_count": len(candidates)},
            }

        # Segments (grid-culled)
        best_seg = None
        best_seg_d = float("inf")
        seg_candidates = self._segment_grid.query(x, y)

        for idx in seg_candidates:
            seg = self.segments[idx]
            x0, y0, x1, y1 = self._segment_bbox[idx]
            # Cheap bbox expansion check
            if x < x0 - seg_radius_px or x > x1 + seg_radius_px or y < y0 - seg_radius_px or y > y1 + seg_radius_px:
                continue
            d = _point_to_polyline_distance(x, y, seg.geometry)
            if d < best_seg_d:
                best_seg, best_seg_d = seg, d

        if best_seg and best_seg_d <= seg_radius_px:
            line = self.lines.get(best_seg.line_id, {})
            return {
                "hit": True,
                "hit_type": "segment",
                "feature": {
                    "id": best_seg.id,
                    "name": best_seg.name,
                    "line_id": best_seg.line_id,
                    "line_name": line.get("name", best_seg.line_id),
                    "mode": line.get("mode", "unknown"),
                },
                "debug": {"nearest_distance_px": best_seg_d, "candidate_count": len(seg_candidates)},
            }

        return {
            "hit": False,
            "hit_type": None,
            "feature": None,
            "debug": {"nearest_distance_px": None, "candidate_count": len(seg_candidates)},
        }
