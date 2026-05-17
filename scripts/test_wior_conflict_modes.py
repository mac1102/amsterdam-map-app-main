from __future__ import annotations

import json
import os
import sys
from datetime import date, timedelta
from pathlib import Path
from typing import Any


os.environ.setdefault("SESSION_SECRET", "test-session-secret")

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from fastapi import HTTPException  # noqa: E402

import backend.main as main  # noqa: E402
from backend.postgis_wior_queries import get_postgis_wior_mirror_status  # noqa: E402
from backend.wior_fetch import get_cached_wior_serving_features, init_wior_db  # noqa: E402


REQUIRED_RESPONSE_KEYS = {"ok", "has_conflicts", "conflict_count", "conflicts"}


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


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


def sample_targets() -> dict[str, list[dict[str, Any]]]:
    rows = get_cached_wior_serving_features(limit=5000, mode="all")
    for row in rows:
        segment_ids = row.get("segment_ids") or []
        start_d = parse_date(row.get("start_date"))
        end_d = parse_date(row.get("end_date"))
        if not segment_ids or not start_d or not end_d:
            continue

        segment_id = segment_ids[0]
        future = date.today() + timedelta(days=3650)
        known = {
            "segment_id": segment_id,
            "target_type": "rail_segment",
            "project_start": f"{start_d.isoformat()}T00:00:00",
            "project_end": f"{end_d.isoformat()}T23:59:59",
            "target_index": 0,
            "schedule_index": 0,
            "schedule_label": row.get("project_code") or "sample",
        }
        return {
            "known": [known],
            "future": [
                {
                    **known,
                    "project_start": f"{future.isoformat()}T00:00:00",
                    "project_end": f"{(future + timedelta(days=1)).isoformat()}T23:59:59",
                }
            ],
            "invalid_segment": [
                {
                    **known,
                    "segment_id": "NOT_A_REAL_SEGMENT",
                }
            ],
        }
    raise RuntimeError("No WIOR serving rows with segment IDs and dates found.")


def response_data(response: Any) -> dict[str, Any]:
    return json.loads(response.body.decode("utf-8"))


def call_conflicts(targets: list[dict[str, Any]], backend: str | None = None) -> tuple[int, dict[str, Any]]:
    payload = main.WiorConflictCheckRequest(targets=targets)
    try:
        if backend is None:
            response = main.api_wior_conflicts_check(payload, object())
        else:
            response = main.api_wior_conflicts_check(payload, object(), backend=backend)
    except HTTPException as exc:
        return exc.status_code, {"detail": exc.detail}
    return response.status_code, response_data(response)


def require_compatible_response(label: str, data: dict[str, Any]) -> None:
    require(REQUIRED_RESPONSE_KEYS <= set(data), f"{label} response shape changed: {data}")
    require(data["ok"] is True, f"{label} should return ok=true")
    require(isinstance(data["has_conflicts"], bool), f"{label} has_conflicts should be boolean")
    require(isinstance(data["conflict_count"], int), f"{label} conflict_count should be integer")
    require(isinstance(data["conflicts"], list), f"{label} conflicts should be a list")
    require(data["conflict_count"] == len(data["conflicts"]), f"{label} conflict_count mismatch")


def print_result(label: str, data: dict[str, Any]) -> None:
    print(
        f"{label}: "
        f"backend={data.get('backend')} "
        f"fallback={data.get('fallback_used')} "
        f"has_conflicts={data.get('has_conflicts')} "
        f"count={data.get('conflict_count')}"
    )


def run_real_mode_checks(targets: dict[str, list[dict[str, Any]]]) -> None:
    status = get_postgis_wior_mirror_status()
    print(f"PostGIS WIOR mirror status: {json.dumps(status, sort_keys=True)}")
    require(status.get("available") is True, f"PostGIS WIOR mirror unavailable: {status}")

    status_code, default_data = call_conflicts(targets["known"])
    require(status_code == 200, f"default mode failed: {status_code} {default_data}")
    require_compatible_response("default", default_data)
    require(default_data.get("backend") == "postgis", "default mode should use PostGIS when available")
    require(default_data.get("fallback_used") is False, "default mode should not fallback when PostGIS succeeds")
    require(default_data["has_conflicts"] is True, "known conflict sample should conflict in default mode")
    print_result("default auto known conflict", default_data)

    status_code, legacy_data = call_conflicts(targets["known"], backend="legacy")
    require(status_code == 200, f"legacy mode failed: {status_code} {legacy_data}")
    require_compatible_response("legacy", legacy_data)
    require(legacy_data["has_conflicts"] is True, "known conflict sample should conflict in legacy mode")
    print_result("legacy known conflict", legacy_data)

    status_code, postgis_data = call_conflicts(targets["known"], backend="postgis")
    require(status_code == 200, f"postgis mode failed: {status_code} {postgis_data}")
    require_compatible_response("postgis", postgis_data)
    require(postgis_data.get("backend") == "postgis", "backend=postgis should report postgis")
    require(postgis_data["has_conflicts"] is True, "known conflict sample should conflict in PostGIS mode")
    print_result("postgis known conflict", postgis_data)

    status_code, compare_data = call_conflicts(targets["known"], backend="compare")
    require(status_code == 200, f"compare mode failed: {status_code} {compare_data}")
    require(compare_data.get("backend") == "compare", "backend=compare should report compare")
    require(compare_data.get("legacy", {}).get("has_conflicts") is True, "compare legacy result should conflict")
    require(compare_data.get("postgis", {}).get("has_conflicts") is True, "compare PostGIS result should conflict")
    require("differences" in compare_data, "compare mode should include differences")
    print(f"compare known conflict: differences={compare_data.get('differences')}")

    for label in ("future", "invalid_segment"):
        status_code, data = call_conflicts(targets[label])
        require(status_code == 200, f"{label} default mode failed: {status_code} {data}")
        require_compatible_response(label, data)
        require(data.get("backend") == "postgis", f"{label} should still use PostGIS")
        require(data["has_conflicts"] is False, f"{label} should not conflict")
        print_result(f"default auto {label}", data)


def run_fallback_checks(targets: dict[str, list[dict[str, Any]]]) -> None:
    original_status = main.get_postgis_wior_mirror_status
    original_find = main.find_wior_conflicts_postgis

    try:
        main.get_postgis_wior_mirror_status = lambda: {
            "database_url_set": True,
            "reachable": True,
            "wior_table_exists": True,
            "tram_segments_table_exists": True,
            "row_count": 0,
            "available": False,
            "reason": "postgis_mirror_empty",
        }
        main.find_wior_conflicts_postgis = lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("default empty-mirror fallback should not call PostGIS conflict helper")
        )

        status_code, data = call_conflicts(targets["known"])
        require(status_code == 200, f"default empty-mirror fallback failed: {status_code} {data}")
        require_compatible_response("default empty-mirror fallback", data)
        require(data.get("backend") == "legacy", "default empty-mirror fallback should use legacy")
        require(data.get("fallback_used") is True, "default empty-mirror fallback should report fallback")
        require(data.get("fallback_reason") == "postgis_mirror_empty", "fallback reason should be postgis_mirror_empty")
        require(data["has_conflicts"] is True, "fallback known conflict sample should still conflict")
        print_result("default empty-mirror fallback", data)

        status_code, data = call_conflicts(targets["known"], backend="postgis")
        require(status_code == 503, f"explicit postgis should not fallback when unavailable: {status_code} {data}")
        print(f"explicit postgis unavailable: status={status_code}")

        main.get_postgis_wior_mirror_status = lambda: {
            "database_url_set": True,
            "reachable": True,
            "wior_table_exists": True,
            "tram_segments_table_exists": True,
            "row_count": 21,
            "available": True,
            "reason": None,
        }
        main.find_wior_conflicts_postgis = lambda *args, **kwargs: (_ for _ in ()).throw(
            RuntimeError("synthetic PostGIS failure")
        )

        status_code, data = call_conflicts(targets["known"])
        require(status_code == 200, f"default PostGIS-error fallback failed: {status_code} {data}")
        require_compatible_response("default PostGIS-error fallback", data)
        require(data.get("backend") == "legacy", "default PostGIS-error fallback should use legacy")
        require(data.get("fallback_used") is True, "default PostGIS-error fallback should report fallback")
        require(data.get("fallback_reason") == "postgis_error", "fallback reason should be postgis_error")
        require(data["has_conflicts"] is True, "error fallback known conflict sample should still conflict")
        print_result("default PostGIS-error fallback", data)
    finally:
        main.get_postgis_wior_mirror_status = original_status
        main.find_wior_conflicts_postgis = original_find


def main_script() -> int:
    init_wior_db()
    original_require_user = main._require_user
    main._require_user = lambda request: {"email": "test@example.com", "is_admin": True}
    try:
        targets = sample_targets()
        print(f"Known target sample: {json.dumps(targets['known'], ensure_ascii=False)}")
        run_real_mode_checks(targets)
        run_fallback_checks(targets)
    finally:
        main._require_user = original_require_user
    return 0


if __name__ == "__main__":
    raise SystemExit(main_script())
