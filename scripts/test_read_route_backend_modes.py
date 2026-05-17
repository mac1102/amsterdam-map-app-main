from __future__ import annotations

import json
import os
import sqlite3
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from fastapi import HTTPException
from fastapi.responses import JSONResponse


os.environ.setdefault("SESSION_SECRET", "test-session-secret")

ROOT = Path(__file__).resolve().parents[1]
SQLITE_DB = ROOT / "backend" / "data" / "app.db"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import backend.main as main  # noqa: E402
from backend.postgres_app_queries import PostgresAppQueries  # noqa: E402


class FakeRequest:
    pass


class Comparison:
    def __init__(self) -> None:
        self.failures: list[str] = []
        self.warnings: list[str] = []

    def pass_(self, label: str) -> None:
        print(f"PASS {label}")

    def fail(self, label: str, detail: str) -> None:
        message = f"FAIL {label}: {detail}"
        self.failures.append(message)
        print(message)

    def warn(self, label: str, detail: str) -> None:
        message = f"WARN {label}: {detail}"
        self.warnings.append(message)
        print(message)


def sqlite_values(sql: str, params: tuple[Any, ...] = ()) -> list[Any]:
    with sqlite3.connect(SQLITE_DB) as conn:
        return [row[0] for row in conn.execute(sql, params).fetchall()]


def valid_segment_ids() -> set[str]:
    with PostgresAppQueries() as pg:
        return {row["segment_id"] for row in pg._conn().execute("SELECT segment_id FROM tram_segments")}


def response_json(response: JSONResponse) -> dict[str, Any]:
    return json.loads(response.body.decode("utf-8"))


def normalize_datetime_string(value: str) -> str:
    raw = value.strip()
    if "T" not in raw:
        return raw
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return value
    if parsed.tzinfo is not None:
        parsed = parsed.replace(tzinfo=None)
    return parsed.isoformat()


def normalize_value(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: normalize_value(value[key]) for key in sorted(value)}
    if isinstance(value, list):
        return [normalize_value(item) for item in value]
    if isinstance(value, str):
        return normalize_datetime_string(value)
    return value


def normalize_known_segment_differences(
    sqlite_value: Any,
    pg_value: Any,
    segments: set[str],
    comparison: Comparison,
    label: str,
) -> tuple[Any, Any]:
    sqlite_copy = json.loads(json.dumps(sqlite_value))
    pg_copy = json.loads(json.dumps(pg_value))

    def walk(left: Any, right: Any, path: str) -> None:
        if isinstance(left, dict) and isinstance(right, dict):
            if "segment_id" in left and "segment_id" in right:
                segment_id = left.get("segment_id")
                if segment_id and segment_id not in segments and right.get("segment_id") is None:
                    comparison.warn(
                        label,
                        f"{path}.segment_id normalized from old pixel/KGE-missing value {segment_id!r} to NULL",
                    )
                    left["segment_id"] = None
            for key in set(left) & set(right):
                walk(left[key], right[key], f"{path}.{key}")
        elif isinstance(left, list) and isinstance(right, list):
            for index, (left_item, right_item) in enumerate(zip(left, right)):
                walk(left_item, right_item, f"{path}[{index}]")

    walk(sqlite_copy, pg_copy, "$")
    return sqlite_copy, pg_copy


def call_route(mode: str, fn: Callable[..., JSONResponse], *args: Any, **kwargs: Any) -> dict[str, Any]:
    os.environ["APP_DB_BACKEND"] = mode
    try:
        response = fn(*args, **kwargs)
    except HTTPException as exc:
        return {"__status_code": exc.status_code, "detail": exc.detail}
    return response_json(response)


def compare_route(
    label: str,
    fn: Callable[..., JSONResponse],
    comparison: Comparison,
    segments: set[str],
    *args: Any,
    **kwargs: Any,
) -> None:
    sqlite_data = call_route("sqlite", fn, *args, **kwargs)
    postgres_data = call_route("postgres", fn, *args, **kwargs)
    sqlite_data, postgres_data = normalize_known_segment_differences(
        sqlite_data,
        postgres_data,
        segments,
        comparison,
        label,
    )
    left = normalize_value(sqlite_data)
    right = normalize_value(postgres_data)
    if left == right:
        comparison.pass_(label)
    else:
        comparison.fail(label, f"sqlite={left!r} postgres={right!r}")


def main_script() -> int:
    comparison = Comparison()
    segments = valid_segment_ids()
    request = FakeRequest()

    original_require_user = main._require_user
    original_require_admin = main._require_admin
    original_backend = os.environ.get("APP_DB_BACKEND")

    current_user = {"email": "storm@gvb.local", "is_admin": False}
    admin_user = {"email": "admin@local.gvb", "is_admin": True}

    main._require_user = lambda req: current_user
    main._require_admin = lambda req: admin_user

    try:
        compare_route("GET /api/my_applications", main.my_applications, comparison, segments, request)

        for email in sqlite_values("SELECT email FROM users ORDER BY email"):
            current_user["email"] = email
            compare_route(
                f"GET /api/my_applications as {email}",
                main.my_applications,
                comparison,
                segments,
                request,
            )
        current_user["email"] = "storm@gvb.local"

        compare_route("GET /api/admin/applications", main.admin_list_applications, comparison, segments, request)
        compare_route(
            "GET /api/admin/applications?status=submitted",
            main.admin_list_applications,
            comparison,
            segments,
            request,
            status="submitted",
        )
        compare_route(
            "GET /api/admin/applications?email=storm",
            main.admin_list_applications,
            comparison,
            segments,
            request,
            email="storm",
        )

        for application_id in sqlite_values("SELECT application_id FROM applications ORDER BY submitted_at DESC"):
            compare_route(
                f"GET /api/admin/applications/{application_id}",
                main.admin_get_application,
                comparison,
                segments,
                application_id,
                request,
            )

        compare_route("GET /api/tbgn/projects", main.api_list_tbgn_projects, comparison, segments, request)
        compare_route("GET /api/admin/tbgn", main.admin_list_tbgn_projects, comparison, segments, request)
        for project_id in sqlite_values("SELECT id FROM tbgn_projects ORDER BY id"):
            compare_route(
                f"GET /api/admin/tbgn/{project_id}",
                main.admin_get_tbgn_project,
                comparison,
                segments,
                project_id,
                request,
            )

        compare_route("GET /api/my_transfer_trips", main.my_transfer_trips, comparison, segments, request)
        for email in sqlite_values("SELECT email FROM users ORDER BY email"):
            current_user["email"] = email
            compare_route(
                f"GET /api/my_transfer_trips as {email}",
                main.my_transfer_trips,
                comparison,
                segments,
                request,
            )
        current_user["email"] = "storm@gvb.local"

        compare_route("GET /api/admin/transfer_trips", main.admin_list_transfer_trips, comparison, segments, request)
        compare_route(
            "GET /api/admin/transfer_trips?status=submitted",
            main.admin_list_transfer_trips,
            comparison,
            segments,
            request,
            status="submitted",
        )
        compare_route(
            "GET /api/admin/transfer_trips?email=storm",
            main.admin_list_transfer_trips,
            comparison,
            segments,
            request,
            email="storm",
        )
        for trip_id in sqlite_values("SELECT transfer_trip_id FROM transfer_trips ORDER BY submitted_at DESC"):
            compare_route(
                f"GET /api/admin/transfer_trips/{trip_id}",
                main.admin_get_transfer_trip,
                comparison,
                segments,
                trip_id,
                request,
            )

        print()
        print(f"warnings: {len(comparison.warnings)}")
        print(f"failures: {len(comparison.failures)}")
        return 1 if comparison.failures else 0
    finally:
        main._require_user = original_require_user
        main._require_admin = original_require_admin
        if original_backend is None:
            os.environ.pop("APP_DB_BACKEND", None)
        else:
            os.environ["APP_DB_BACKEND"] = original_backend


if __name__ == "__main__":
    raise SystemExit(main_script())
