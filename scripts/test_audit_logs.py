from __future__ import annotations

import asyncio
import io
import json
import os
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import psycopg
from fastapi import HTTPException
from psycopg.rows import dict_row
from starlette.datastructures import Headers, UploadFile


os.environ.setdefault("SESSION_SECRET", "test-session-secret")

ROOT = Path(__file__).resolve().parents[1]
UPLOADS_DIR = ROOT / "backend" / "data" / "uploads"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import backend.main as main  # noqa: E402
from backend.audit_logs import get_database_url, write_audit_log  # noqa: E402
from backend.wior_fetch import get_cached_wior_serving_features, init_wior_db  # noqa: E402


USER_EMAIL = "phase10-user@gvb.local"
ADMIN_EMAIL = "phase10-admin@gvb.local"
PASSWORD = "phase10-test-password"


class FakeClient:
    host = "phase10-test"


class FakeRequest:
    def __init__(
        self,
        body: dict[str, Any] | None = None,
        user: dict[str, Any] | None = None,
    ) -> None:
        self._body = body or {}
        self.session: dict[str, Any] = {}
        if user:
            self.session["user"] = user
        self.client = FakeClient()
        self.headers = Headers({"user-agent": "phase10-audit-test"})

    async def json(self) -> dict[str, Any]:
        return self._body


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def response_json(response: Any) -> dict[str, Any]:
    return json.loads(response.body.decode("utf-8"))


def connect() -> psycopg.Connection[dict[str, Any]]:
    url = get_database_url()
    if not url:
        raise RuntimeError("DATABASE_URL is not set")
    return psycopg.connect(url, row_factory=dict_row)


def query_value(sql: str, params: tuple[Any, ...] = ()) -> Any:
    with connect() as conn:
        row = conn.execute(sql, params).fetchone()
    return next(iter(row.values())) if row else None


def execute(sql: str, params: tuple[Any, ...] = ()) -> None:
    with connect() as conn:
        with conn.transaction():
            conn.execute(sql, params)


def ensure_users() -> None:
    with connect() as conn:
        with conn.transaction():
            for email, is_admin in ((USER_EMAIL, False), (ADMIN_EMAIL, True)):
                conn.execute(
                    """
                    INSERT INTO users (email, password_hash, created_at, is_admin)
                    VALUES (%s, %s, %s, %s)
                    ON CONFLICT (email)
                    DO UPDATE SET password_hash = EXCLUDED.password_hash,
                                  is_admin = EXCLUDED.is_admin
                    """,
                    (
                        email,
                        main.hash_password(PASSWORD),
                        datetime.now(timezone.utc).isoformat(),
                        is_admin,
                    ),
                )


def cleanup(application_id: str | None) -> None:
    with connect() as conn:
        with conn.transaction():
            if application_id:
                conn.execute("DELETE FROM applications WHERE application_id = %s", (application_id,))
            conn.execute("DELETE FROM audit_logs WHERE actor_email IN (%s, %s)", (USER_EMAIL, ADMIN_EMAIL))
            conn.execute("DELETE FROM users WHERE email IN (%s, %s)", (USER_EMAIL, ADMIN_EMAIL))
    if application_id:
        for path in UPLOADS_DIR.glob(f"{application_id}__phase10_test.pdf"):
            path.unlink(missing_ok=True)


def first_segment() -> dict[str, Any]:
    with connect() as conn:
        row = conn.execute(
            """
            SELECT segment_id, line_id, line_name
            FROM tram_segments
            WHERE bookable = true
            ORDER BY segment_id
            LIMIT 1
            """
        ).fetchone()
    if not row:
        raise RuntimeError("No tram_segments rows available for audit test")
    return dict(row)


def make_upload() -> UploadFile:
    content = b"%PDF-1.4\n1 0 obj <<>> endobj\ntrailer <<>>\n%%EOF\n"
    return UploadFile(
        file=io.BytesIO(content),
        filename="phase10_test.pdf",
        headers=Headers({"content-type": "application/pdf"}),
    )


def parse_date(value: Any) -> date | None:
    if value is None:
        return None
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def known_wior_target() -> list[dict[str, Any]]:
    init_wior_db()
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
                }
            ]
    raise RuntimeError("No WIOR serving rows with segment IDs and dates found")


def assert_schema_and_views() -> None:
    for name in ("audit_logs", "user_activity_view", "admin_activity_view", "system_activity_view"):
        exists = query_value("SELECT to_regclass(%s) IS NOT NULL AS exists", (f"public.{name}",))
        require(bool(exists), f"{name} does not exist")
    print("PASS audit_logs schema and views")


def assert_direct_write() -> None:
    write_audit_log(
        actor_email=USER_EMAIL,
        actor_type="user",
        action_scope="user_action",
        action="phase10_direct_write",
        entity_type="test",
        entity_id="direct",
        metadata={"password": "should-not-store", "safe": "ok"},
    )
    row = query_value(
        """
        SELECT COUNT(*)::int
        FROM audit_logs
        WHERE actor_email = %s
          AND action = 'phase10_direct_write'
          AND metadata::text NOT ILIKE '%%password%%'
        """,
        (USER_EMAIL,),
    )
    require(int(row or 0) >= 1, "write_audit_log did not insert sanitized row")
    print("PASS write_audit_log insert and sanitization")


async def assert_login_audit() -> None:
    ok_response = await main.login(FakeRequest({"email": USER_EMAIL, "password": PASSWORD}))
    ok_data = response_json(ok_response)
    require(ok_data["ok"] is True, "login_success route failed")

    try:
        await main.login(FakeRequest({"email": USER_EMAIL, "password": "wrong-password"}))
    except HTTPException as exc:
        require(exc.status_code == 401, "login_failed should return 401")
    else:
        raise AssertionError("login_failed test unexpectedly succeeded")

    count = query_value(
        """
        SELECT COUNT(*)::int
        FROM audit_logs
        WHERE actor_email = %s
          AND action IN ('login_success', 'login_failed')
          AND coalesce(metadata::text, '') NOT ILIKE '%%wrong-password%%'
          AND coalesce(metadata::text, '') NOT ILIKE '%%password_hash%%'
        """,
        (USER_EMAIL,),
    )
    require(int(count or 0) >= 2, "login audit rows missing or unsafe")
    print("PASS login_success/login_failed audit without password data")


async def create_application_and_audit() -> str:
    segment = first_segment()
    project_date = date.today() + timedelta(days=3650)
    payload = {
        "targets": [
            {
                "target_type": "rail_segment",
                "asset_id": segment["segment_id"],
                "asset_label": f"Phase 10 test segment {segment['segment_id']}",
                "asset_source": "SPOOR_DATA",
                "segment_id": segment["segment_id"],
                "line_id": segment.get("line_id") or "",
                "line_name": segment.get("line_name") or "",
                "work_mode": "whole-segment",
                "schedules": [
                    {
                        "project_start": f"{project_date.isoformat()}T09:00:00",
                        "project_end": f"{project_date.isoformat()}T11:00:00",
                        "label": "Phase 10 test",
                    }
                ],
            }
        ],
        "person_mode": "single",
        "shared_person": {
            "first_name": "Phase",
            "last_name": "Ten",
            "phone": "+31000000000",
            "email": USER_EMAIL,
            "employee_id": "phase10",
        },
        "work_details": {
            "description": "Phase 10 audit test",
            "source": "test",
            "urgency": "low",
            "affected_lines": segment.get("line_id") or "",
            "notes": "temporary test data",
        },
        "contact_details": {
            "coordinator": "Phase 10 Test",
            "vvw_measure": "none",
        },
    }
    response = await main.apply_for_project(
        FakeRequest(user={"email": USER_EMAIL, "is_admin": False}),
        payload_json=json.dumps(payload),
        safety_plans=[make_upload()],
    )
    data = response_json(response)
    application_id = data["application_id"]
    count = query_value(
        """
        SELECT COUNT(*)::int
        FROM audit_logs
        WHERE actor_email = %s
          AND entity_id = %s
          AND action IN ('application_submitted', 'file_upload_metadata_saved')
        """,
        (USER_EMAIL, application_id),
    )
    require(int(count or 0) >= 2, "application submission audit rows missing")
    print("PASS application submission audit")
    return application_id


async def assert_admin_status_audit(application_id: str) -> None:
    response = await main.admin_update_application_status(
        application_id,
        FakeRequest(
            {"status": "approved", "admin_note": "phase10 approved", "decision_message": "phase10 decision"},
            user={"email": ADMIN_EMAIL, "is_admin": True},
        ),
    )
    data = response_json(response)
    require(data["status"] == "approved", "admin status update failed")
    row = query_value(
        """
        SELECT COUNT(*)::int
        FROM audit_logs
        WHERE actor_email = %s
          AND entity_id = %s
          AND action = 'application_status_changed'
          AND old_value->>'status' = 'submitted'
          AND new_value->>'status' = 'approved'
        """,
        (ADMIN_EMAIL, application_id),
    )
    require(int(row or 0) >= 1, "admin status audit row missing")
    print("PASS admin status update audit")


def assert_activity_endpoints(application_id: str) -> None:
    user_response = main.settings_activity(
        FakeRequest(user={"email": USER_EMAIL, "is_admin": False}),
        limit=50,
    )
    user_data = response_json(user_response)
    require(user_data["ok"] is True, "settings activity failed")
    require(user_data["items"], "settings activity returned no rows")
    require(all(item.get("actor_email") == USER_EMAIL for item in user_data["items"]), "settings activity leaked another actor")
    require(all("password_hash" not in json.dumps(item).lower() for item in user_data["items"]), "settings activity exposed password hash")

    try:
        main.admin_audit_logs(FakeRequest(user={"email": USER_EMAIL, "is_admin": False}))
    except HTTPException as exc:
        require(exc.status_code == 403, "normal user should get 403 for admin audit logs")
    else:
        raise AssertionError("normal user accessed admin audit logs")

    admin_response = main.admin_audit_logs(
        FakeRequest(user={"email": ADMIN_EMAIL, "is_admin": True}),
        entity_type="application",
        entity_id=application_id,
        limit=20,
    )
    admin_data = response_json(admin_response)
    require(admin_data["ok"] is True, "admin audit endpoint failed")
    require(any(item.get("action") == "application_status_changed" for item in admin_data["items"]), "admin audit endpoint missing status row")
    print("PASS settings/admin activity endpoints")


def assert_wior_audit() -> None:
    targets = known_wior_target()
    payload = main.WiorConflictCheckRequest(targets=targets)
    response = main.api_wior_conflicts_check(
        payload,
        FakeRequest(user={"email": USER_EMAIL, "is_admin": False}),
    )
    data = response_json(response)
    require(data["ok"] is True, "WIOR conflict check failed")
    row = query_value(
        """
        SELECT metadata
        FROM audit_logs
        WHERE actor_email = %s
          AND action = 'wior_conflict_checked'
        ORDER BY created_at DESC, id DESC
        LIMIT 1
        """,
        (USER_EMAIL,),
    )
    require(isinstance(row, dict), "WIOR audit metadata missing")
    require("target_count" in row and "conflict_count" in row and "backend" in row, "WIOR audit metadata incomplete")
    require("geometry" not in json.dumps(row).lower(), "WIOR audit metadata should not include geometry")
    print("PASS WIOR conflict audit metadata")


async def run_checks() -> None:
    original_backend = os.environ.get("APP_DB_BACKEND")
    os.environ["APP_DB_BACKEND"] = "postgres"
    application_id: str | None = None
    try:
        cleanup(None)
        assert_schema_and_views()
        ensure_users()
        assert_direct_write()
        await assert_login_audit()
        application_id = await create_application_and_audit()
        await assert_admin_status_audit(application_id)
        assert_activity_endpoints(application_id)
        assert_wior_audit()
    finally:
        cleanup(application_id)
        if original_backend is None:
            os.environ.pop("APP_DB_BACKEND", None)
        else:
            os.environ["APP_DB_BACKEND"] = original_backend


def main_script() -> int:
    asyncio.run(run_checks())
    return 0


if __name__ == "__main__":
    raise SystemExit(main_script())
