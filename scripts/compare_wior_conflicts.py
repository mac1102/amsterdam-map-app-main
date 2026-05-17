from __future__ import annotations

import json
import os
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any


os.environ.setdefault("SESSION_SECRET", "test-session-secret")

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.postgis_wior_queries import find_wior_conflicts_postgis, is_postgis_wior_available  # noqa: E402
from backend.wior_fetch import get_cached_wior_serving_features, init_wior_db  # noqa: E402


def parse_date(value: Any) -> date | None:
    if value is None:
        return None
    raw = str(value).strip()
    if not raw:
        return None
    try:
        return date.fromisoformat(raw[:10])
    except ValueError:
        return None


def ranges_overlap(project_start: str, project_end: str, wior_start: str, wior_end: str) -> bool:
    try:
        permit_start = datetime.fromisoformat(project_start).date()
        permit_end = datetime.fromisoformat(project_end).date()
    except ValueError:
        return False
    start_d = parse_date(wior_start)
    end_d = parse_date(wior_end)
    if not start_d or not end_d:
        return False
    return start_d <= permit_end and end_d >= permit_start


def legacy_conflicts(targets: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows = get_cached_wior_serving_features(limit=5000, mode="all")
    conflicts: list[dict[str, Any]] = []
    for target_index, target in enumerate(targets):
        if target.get("target_type") == "overhead_section":
            continue
        segment_id = str(target.get("segment_id") or "").strip()
        if not segment_id:
            continue
        for wior in rows:
            if segment_id not in (wior.get("segment_ids") or []):
                continue
            if not ranges_overlap(
                str(target.get("project_start") or ""),
                str(target.get("project_end") or ""),
                str(wior.get("start_date") or ""),
                str(wior.get("end_date") or ""),
            ):
                continue
            conflicts.append(
                {
                    "target_index": target.get("target_index", target_index),
                    "matched_segment_id": segment_id,
                    "wior_id": wior.get("wior_id"),
                    "project_code": wior.get("project_code"),
                    "project_name": wior.get("project_name"),
                    "start_date": wior.get("start_date"),
                    "end_date": wior.get("end_date"),
                }
            )
    return conflicts


def conflict_refs(conflicts: list[dict[str, Any]]) -> set[tuple[str | None, str | None]]:
    return {
        (item.get("wior_id"), item.get("matched_segment_id"))
        for item in conflicts
    }


def print_case(label: str, targets: list[dict[str, Any]]) -> None:
    old = legacy_conflicts(targets)
    try:
        new = find_wior_conflicts_postgis(targets, buffer_m=10.0)
        postgis_error = None
    except Exception as exc:
        new = []
        postgis_error = str(exc)

    old_refs = conflict_refs(old)
    new_refs = conflict_refs(new)
    print(f"\n{label}")
    print(f"targets: {json.dumps(targets, ensure_ascii=False)}")
    print(f"old conflict count: {len(old)}")
    print(f"PostGIS conflict count: {len(new)}")
    if postgis_error:
        print(f"PostGIS error: {postgis_error}")
    print(f"matching references: {len(old_refs & new_refs)}")
    legacy_only = sorted(old_refs - new_refs)
    postgis_only = sorted(new_refs - old_refs)
    if legacy_only:
        print(f"warning: legacy-only references: {legacy_only[:10]}")
    if postgis_only:
        print(f"warning: PostGIS-only references: {postgis_only[:10]}")


def sample_targets() -> list[tuple[str, list[dict[str, Any]]]]:
    rows = get_cached_wior_serving_features(limit=5000, mode="all")
    sample = None
    for row in rows:
        segment_ids = row.get("segment_ids") or []
        start_d = parse_date(row.get("start_date"))
        end_d = parse_date(row.get("end_date"))
        if segment_ids and start_d and end_d:
            sample = (row, segment_ids[0], start_d, end_d)
            break
    if sample is None:
        return []

    row, segment_id, start_d, end_d = sample
    future = date.today() + timedelta(days=3650)
    return [
        (
            "known segment/date from WIOR serving cache",
            [
                {
                    "segment_id": segment_id,
                    "target_type": "rail_segment",
                    "project_start": f"{start_d.isoformat()}T00:00:00",
                    "project_end": f"{end_d.isoformat()}T23:59:59",
                    "target_index": 0,
                    "schedule_index": 0,
                    "schedule_label": row.get("project_code") or "sample",
                }
            ],
        ),
        (
            "same segment far future no-conflict sample",
            [
                {
                    "segment_id": segment_id,
                    "target_type": "rail_segment",
                    "project_start": f"{future.isoformat()}T00:00:00",
                    "project_end": f"{(future + timedelta(days=1)).isoformat()}T23:59:59",
                }
            ],
        ),
        (
            "outside segment ID sample",
            [
                {
                    "segment_id": "NOT_A_REAL_SEGMENT",
                    "target_type": "rail_segment",
                    "project_start": f"{start_d.isoformat()}T00:00:00",
                    "project_end": f"{end_d.isoformat()}T23:59:59",
                }
            ],
        ),
    ]


def main() -> int:
    init_wior_db()
    print(f"PostGIS WIOR available: {is_postgis_wior_available()}")
    cases = sample_targets()
    if not cases:
        print("warning: no WIOR serving rows with segment IDs and dates found; nothing to compare.")
        return 0
    for label, targets in cases:
        print_case(label, targets)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
