from __future__ import annotations

import json
import os
import sys
from datetime import date
from pathlib import Path
from typing import Any


os.environ.setdefault("SESSION_SECRET", "test-session-secret")

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from fastapi import HTTPException  # noqa: E402

from backend.postgis_wior_queries import get_postgis_wior_mirror_status  # noqa: E402
from backend.wior_fetch import get_cached_wior_serving_features  # noqa: E402
from backend.wior_refresh_and_sync_job import run_wior_refresh_and_sync_job  # noqa: E402


WIOR_DB = ROOT / "backend" / "wior.db"
APP_DB = ROOT / "backend" / "data" / "app.db"
REQUIRED_RESPONSE_KEYS = {"ok", "has_conflicts", "conflict_count", "conflicts"}


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def db_stat(path: Path) -> tuple[int, int]:
    stat = path.stat()
    return (stat.st_size, stat.st_mtime_ns)


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


def known_conflict_target() -> list[dict[str, Any]]:
    rows = get_cached_wior_serving_features(limit=5000, mode="all")
    for row in rows:
        segment_ids = row.get("segment_ids") or []
        start_d = parse_date(row.get("start_date"))
        end_d = parse_date(row.get("end_date"))
        if segment_ids and start_d and end_d:
            return [
                {
                    "segment_id": segment_ids[0],
                    "target_type": "rail_segment",
                    "project_start": f"{start_d.isoformat()}T00:00:00",
                    "project_end": f"{end_d.isoformat()}T23:59:59",
                    "target_index": 0,
                    "schedule_index": 0,
                    "schedule_label": row.get("project_code") or "sample",
                }
            ]
    raise RuntimeError("No WIOR serving rows with segment IDs and dates found.")


def response_data(response: Any) -> dict[str, Any]:
    return json.loads(response.body.decode("utf-8"))


def call_conflicts(targets: list[dict[str, Any]], backend: str | None = None) -> tuple[int, dict[str, Any]]:
    import backend.main as main

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


def main_script() -> int:
    require(os.getenv("DATABASE_URL", "").strip(), "DATABASE_URL must be set")
    require(APP_DB.exists(), f"app.db does not exist: {APP_DB}")

    app_db_before = db_stat(APP_DB)
    result = run_wior_refresh_and_sync_job()
    app_db_after = db_stat(APP_DB)

    require(result.get("ok") is True, f"combined job failed: {result}")
    require(WIOR_DB.exists(), f"WIOR cache missing after combined job: {WIOR_DB}")
    require(app_db_before == app_db_after, "combined WIOR job should not modify backend/data/app.db")

    sync_result = result.get("postgis_sync") or {}
    if sync_result.get("skipped"):
        reason = sync_result.get("skip_reason") or ""
        require(reason, "skipped sync should report skip_reason")
        print(f"PostGIS WIOR sync skipped: {reason}.")
    else:
        print(
            "PostGIS WIOR sync executed: "
            f"rows_upserted={sync_result.get('rows_upserted')} "
            f"source_rows={sync_result.get('source_serving_rows')}"
        )

    status = get_postgis_wior_mirror_status()
    print(f"PostGIS WIOR mirror status: {json.dumps(status, sort_keys=True)}")
    require(status.get("available") is True, f"PostGIS WIOR mirror unavailable: {status}")
    require(int(status.get("row_count") or 0) > 0, "wior_work_areas should have mirrored rows")

    import backend.main as main

    original_require_user = main._require_user
    main._require_user = lambda request: {"email": "test@example.com", "is_admin": True}
    try:
        targets = known_conflict_target()

        status_code, default_data = call_conflicts(targets)
        require(status_code == 200, f"default conflict endpoint failed: {status_code} {default_data}")
        require_compatible_response("default conflict endpoint", default_data)
        require(default_data.get("backend") == "postgis", "default conflict endpoint should use PostGIS")
        require(default_data["has_conflicts"] is True, "default conflict endpoint should find known conflict")
        print(
            "default conflict endpoint: "
            f"backend={default_data.get('backend')} count={default_data.get('conflict_count')}"
        )

        status_code, legacy_data = call_conflicts(targets, backend="legacy")
        require(status_code == 200, f"legacy conflict endpoint failed: {status_code} {legacy_data}")
        require_compatible_response("legacy conflict endpoint", legacy_data)
        require(legacy_data["has_conflicts"] is True, "legacy conflict endpoint should remain available")
        print(f"legacy conflict endpoint: count={legacy_data.get('conflict_count')}")
    finally:
        main._require_user = original_require_user

    return 0


if __name__ == "__main__":
    raise SystemExit(main_script())
