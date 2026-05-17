from __future__ import annotations

import json
import os
import sqlite3
import sys
import asyncio
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlencode


os.environ.setdefault("SESSION_SECRET", "test-session-secret")

ROOT = Path(__file__).resolve().parents[1]
SQLITE_DB = ROOT / "backend" / "data" / "app.db"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

try:
    from fastapi.testclient import TestClient as FastApiTestClient  # noqa: E402
except Exception as exc:  # pragma: no cover - exercised when httpx is not installed.
    FastApiTestClient = None  # type: ignore[assignment]
    TESTCLIENT_IMPORT_ERROR = exc
else:
    TESTCLIENT_IMPORT_ERROR = None

import backend.main as main  # noqa: E402
from backend.postgres_app_queries import PostgresAppQueries  # noqa: E402


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


class SimpleResponse:
    def __init__(self, status_code: int, body: bytes) -> None:
        self.status_code = status_code
        self._body = body
        self.text = body.decode("utf-8", errors="replace")

    def json(self) -> Any:
        return json.loads(self.text)


class AsgiGetClient:
    """Small GET-only ASGI client used when fastapi.testclient lacks httpx."""

    def __init__(self, app: Any) -> None:
        self.app = app

    def __enter__(self) -> "AsgiGetClient":
        return self

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
        return None

    def get(self, path: str, params: dict[str, Any] | None = None) -> SimpleResponse:
        return asyncio.run(self._get(path, params or {}))

    async def _get(self, path: str, params: dict[str, Any]) -> SimpleResponse:
        query_string = urlencode(params, doseq=True).encode("ascii")
        status_code = 500
        body_parts: list[bytes] = []
        request_sent = False

        scope = {
            "type": "http",
            "asgi": {"version": "3.0", "spec_version": "2.3"},
            "http_version": "1.1",
            "method": "GET",
            "scheme": "http",
            "path": path,
            "raw_path": path.encode("ascii"),
            "query_string": query_string,
            "root_path": "",
            "headers": [(b"host", b"testserver")],
            "client": ("testclient", 50000),
            "server": ("testserver", 80),
        }

        async def receive() -> dict[str, Any]:
            nonlocal request_sent
            if not request_sent:
                request_sent = True
                return {"type": "http.request", "body": b"", "more_body": False}
            return {"type": "http.disconnect"}

        async def send(message: dict[str, Any]) -> None:
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = int(message["status"])
            elif message["type"] == "http.response.body":
                body_parts.append(message.get("body", b""))

        await self.app(scope, receive, send)
        return SimpleResponse(status_code, b"".join(body_parts))


def sqlite_values(sql: str, params: tuple[Any, ...] = ()) -> list[Any]:
    with sqlite3.connect(SQLITE_DB) as conn:
        return [row[0] for row in conn.execute(sql, params).fetchall()]


def valid_segment_ids() -> set[str]:
    with PostgresAppQueries() as pg:
        return {row["segment_id"] for row in pg._conn().execute("SELECT segment_id FROM tram_segments")}


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


def client_get_json(client: Any, mode: str, path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
    os.environ["APP_DB_BACKEND"] = mode
    response = client.get(path, params=params or {})
    try:
        body = response.json()
    except ValueError:
        body = {"__body": response.text}
    return {
        "__status_code": response.status_code,
        "__json": body,
    }


def compare_http_route(
    client: Any,
    label: str,
    path: str,
    comparison: Comparison,
    segments: set[str],
    params: dict[str, Any] | None = None,
) -> None:
    sqlite_data = client_get_json(client, "sqlite", path, params=params)
    postgres_data = client_get_json(client, "postgres", path, params=params)
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

    original_backend = os.environ.get("APP_DB_BACKEND")
    original_require_user = main._require_user
    original_require_admin = main._require_admin

    users = sqlite_values("SELECT email FROM users ORDER BY email")
    application_ids = sqlite_values("SELECT application_id FROM applications ORDER BY submitted_at DESC")
    project_ids = sqlite_values("SELECT id FROM tbgn_projects ORDER BY id")
    trip_ids = sqlite_values("SELECT transfer_trip_id FROM transfer_trips ORDER BY submitted_at DESC")

    current_user = {"email": users[0] if users else "test@example.com", "is_admin": False}
    admin_user = {"email": "admin@local.gvb", "is_admin": True}

    main._require_user = lambda request: current_user
    main._require_admin = lambda request: admin_user

    try:
        client_factory = FastApiTestClient if FastApiTestClient is not None else AsgiGetClient
        if FastApiTestClient is None:
            print(
                "INFO using fallback ASGI GET client because fastapi.testclient is unavailable: "
                f"{TESTCLIENT_IMPORT_ERROR}"
            )

        with client_factory(main.app) as client:
            compare_http_route(
                client,
                "GET /api/my_applications",
                "/api/my_applications",
                comparison,
                segments,
            )
            for email in users:
                current_user["email"] = email
                compare_http_route(
                    client,
                    f"GET /api/my_applications as {email}",
                    "/api/my_applications",
                    comparison,
                    segments,
                )

            compare_http_route(
                client,
                "GET /api/admin/applications",
                "/api/admin/applications",
                comparison,
                segments,
            )
            for application_id in application_ids:
                compare_http_route(
                    client,
                    f"GET /api/admin/applications/{application_id}",
                    f"/api/admin/applications/{application_id}",
                    comparison,
                    segments,
                )

            compare_http_route(
                client,
                "GET /api/tbgn/projects",
                "/api/tbgn/projects",
                comparison,
                segments,
            )
            compare_http_route(
                client,
                "GET /api/admin/tbgn",
                "/api/admin/tbgn",
                comparison,
                segments,
            )
            if not project_ids:
                comparison.warn("GET /api/admin/tbgn/{project_id}", "no tbgn_projects rows to test")
            for project_id in project_ids:
                compare_http_route(
                    client,
                    f"GET /api/admin/tbgn/{project_id}",
                    f"/api/admin/tbgn/{project_id}",
                    comparison,
                    segments,
                )

            if users:
                current_user["email"] = users[0]
            compare_http_route(
                client,
                "GET /api/my_transfer_trips",
                "/api/my_transfer_trips",
                comparison,
                segments,
            )
            for email in users:
                current_user["email"] = email
                compare_http_route(
                    client,
                    f"GET /api/my_transfer_trips as {email}",
                    "/api/my_transfer_trips",
                    comparison,
                    segments,
                )

            compare_http_route(
                client,
                "GET /api/admin/transfer_trips",
                "/api/admin/transfer_trips",
                comparison,
                segments,
            )
            if not trip_ids:
                comparison.warn("GET /api/admin/transfer_trips/{trip_id}", "no transfer_trips rows to test")
            for trip_id in trip_ids:
                compare_http_route(
                    client,
                    f"GET /api/admin/transfer_trips/{trip_id}",
                    f"/api/admin/transfer_trips/{trip_id}",
                    comparison,
                    segments,
                )
    finally:
        main._require_user = original_require_user
        main._require_admin = original_require_admin
        if original_backend is None:
            os.environ.pop("APP_DB_BACKEND", None)
        else:
            os.environ["APP_DB_BACKEND"] = original_backend

    print()
    print(f"warnings: {len(comparison.warnings)}")
    print(f"failures: {len(comparison.failures)}")
    return 1 if comparison.failures else 0


if __name__ == "__main__":
    raise SystemExit(main_script())
