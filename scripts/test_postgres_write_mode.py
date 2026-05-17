from __future__ import annotations

import argparse
import asyncio
import io
import json
import os
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from fastapi import HTTPException
from starlette.datastructures import Headers, UploadFile


os.environ.setdefault("SESSION_SECRET", "test-session-secret")

ROOT = Path(__file__).resolve().parents[1]
UPLOADS_DIR = ROOT / "backend" / "data" / "uploads"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import backend.main as main  # noqa: E402
from backend.postgres_app_queries import PostgresAppQueries, get_database_url  # noqa: E402


TEST_EMAIL = "phase8d-postgres-write-test@gvb.local"
TEST_PASSWORD = "phase8d-test-password"


class FakeClient:
    host = "phase8d-test"


class FakeRequest:
    def __init__(self, body: dict[str, Any] | None = None) -> None:
        self._body = body or {}
        self.session: dict[str, Any] = {}
        self.client = FakeClient()

    async def json(self) -> dict[str, Any]:
        return self._body


def response_json(response: Any) -> dict[str, Any]:
    return json.loads(response.body.decode("utf-8"))


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def local_database_url_required(allow_nonlocal: bool) -> None:
    url = get_database_url()
    if not url:
        raise RuntimeError("DATABASE_URL is not set")
    if not allow_nonlocal and "localhost" not in url and "127.0.0.1" not in url:
        raise RuntimeError("Refusing to run write-mode test against a non-local DATABASE_URL")


def ensure_test_user() -> None:
    with PostgresAppQueries() as pg:
        with pg._conn().transaction():
            pg._conn().execute(
                """
                INSERT INTO users (email, password_hash, created_at, is_admin)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (email)
                DO UPDATE SET password_hash = EXCLUDED.password_hash, is_admin = EXCLUDED.is_admin
                """,
                (
                    TEST_EMAIL,
                    main.hash_password(TEST_PASSWORD),
                    datetime.now(timezone.utc).isoformat(),
                    True,
                ),
            )


def first_segment() -> dict[str, Any]:
    with PostgresAppQueries() as pg:
        row = pg._conn().execute(
            """
            SELECT segment_id, line_id, line_name
            FROM tram_segments
            WHERE bookable = true
            ORDER BY segment_id
            LIMIT 1
            """
        ).fetchone()
    if not row:
        raise RuntimeError("No tram_segments rows available for write-mode test")
    return dict(row)


def first_transfer_stops() -> tuple[int, int] | None:
    with PostgresAppQueries() as pg:
        row = pg._conn().execute(
            """
            SELECT start_stop_id, end_stop_id
            FROM transfer_trips
            ORDER BY submitted_at DESC
            LIMIT 1
            """
        ).fetchone()
    if row:
        return int(row["start_stop_id"]), int(row["end_stop_id"])
    stop_ids = sorted(main._HALTES_SNAPPED)
    if len(stop_ids) >= 2:
        return int(stop_ids[0]), int(stop_ids[1])
    return None


def cleanup_rows(application_id: str | None, transfer_trip_id: str | None, tbgn_id: str | None) -> None:
    with PostgresAppQueries() as pg:
        with pg._conn().transaction():
            if application_id:
                pg._conn().execute("DELETE FROM applications WHERE application_id = %s", (application_id,))
            if transfer_trip_id:
                pg._conn().execute("DELETE FROM transfer_trips WHERE transfer_trip_id = %s", (transfer_trip_id,))
            if tbgn_id:
                pg._conn().execute("DELETE FROM tbgn_projects WHERE id = %s", (tbgn_id,))
            pg._conn().execute("DELETE FROM users WHERE email = %s", (TEST_EMAIL,))

    if application_id:
        for path in UPLOADS_DIR.glob(f"{application_id}__phase8d_test.pdf"):
            path.unlink(missing_ok=True)


def make_upload() -> UploadFile:
    content = b"%PDF-1.4\n1 0 obj <<>> endobj\ntrailer <<>>\n%%EOF\n"
    return UploadFile(
        file=io.BytesIO(content),
        filename="phase8d_test.pdf",
        headers=Headers({"content-type": "application/pdf"}),
    )


async def run_checks() -> None:
    original_backend = os.environ.get("APP_DB_BACKEND")
    original_require_user = main._require_user
    original_require_admin = main._require_admin
    os.environ["APP_DB_BACKEND"] = "postgres"

    application_id: str | None = None
    transfer_trip_id: str | None = None
    tbgn_id: str | None = None

    main._require_user = lambda request: {"email": TEST_EMAIL, "is_admin": False}
    main._require_admin = lambda request: {"email": TEST_EMAIL, "is_admin": True}

    try:
        ensure_test_user()

        login_response = await main.login(FakeRequest({"email": TEST_EMAIL, "password": TEST_PASSWORD}))
        login_data = response_json(login_response)
        require(login_data["ok"] is True, "PostgreSQL login route did not return ok")
        require(login_data["user"]["email"] == TEST_EMAIL, "PostgreSQL login returned wrong user")
        require("password_hash" not in login_data["user"], "login response exposed password_hash")
        print("PASS postgres login")

        segment = first_segment()
        project_date = date.today() + timedelta(days=3650)
        project_start = f"{project_date.isoformat()}T09:00:00"
        project_end = f"{project_date.isoformat()}T11:00:00"
        payload = {
            "targets": [
                {
                    "target_type": "rail_segment",
                    "asset_id": segment["segment_id"],
                    "asset_label": f"Phase 8D test segment {segment['segment_id']}",
                    "asset_source": "SPOOR_DATA",
                    "segment_id": segment["segment_id"],
                    "line_id": segment.get("line_id") or "",
                    "line_name": segment.get("line_name") or "",
                    "work_mode": "whole-segment",
                    "schedules": [
                        {
                            "project_start": project_start,
                            "project_end": project_end,
                            "label": "Phase 8D test",
                        }
                    ],
                }
            ],
            "person_mode": "single",
            "shared_person": {
                "first_name": "Phase",
                "last_name": "EightD",
                "phone": "+31000000000",
                "email": TEST_EMAIL,
                "employee_id": "phase8d",
            },
            "work_details": {
                "description": "Phase 8D PostgreSQL write-mode test",
                "source": "test",
                "urgency": "low",
                "affected_lines": segment.get("line_id") or "",
                "notes": "temporary test data",
            },
            "contact_details": {
                "coordinator": "Phase 8D Test",
                "vvw_measure": "none",
            },
        }
        apply_response = await main.apply_for_project(
            FakeRequest(),
            payload_json=json.dumps(payload),
            safety_plans=[make_upload()],
        )
        apply_data = response_json(apply_response)
        application_id = apply_data["application_id"]
        require(apply_data["ok"] is True, "application write did not return ok")
        print(f"PASS postgres application create {application_id}")

        detail_response = main.admin_get_application(application_id, FakeRequest())
        detail = response_json(detail_response)
        require(detail["application_id"] == application_id, "application read-after-write missing detail")
        require(detail["targets"][0]["segment_id"] == segment["segment_id"], "application target segment_id was not preserved")
        require(detail["uploads"][0]["filename"] == "phase8d_test.pdf", "upload metadata was not written")
        print("PASS postgres application read-after-write and upload metadata")

        week_start = project_date - timedelta(days=project_date.weekday())
        bookings = response_json(
            main.segment_bookings(
                FakeRequest(),
                week_start=week_start.isoformat(),
                target_type="rail_segment",
                asset_id=segment["segment_id"],
            )
        )
        require(
            any(str(item.get("asset_label") or "").startswith("Phase 8D test segment") for item in bookings["bookings"]),
            "segment_bookings did not read PostgreSQL write",
        )
        print("PASS postgres segment bookings read-after-write")

        status_response = await main.admin_update_application_status(
            application_id,
            FakeRequest(
                {
                    "status": "approved",
                    "admin_note": "phase8d approved",
                    "decision_message": "phase8d decision",
                }
            ),
        )
        status_data = response_json(status_response)
        require(status_data["status"] == "approved", "application status update failed")
        updated_detail = response_json(main.admin_get_application(application_id, FakeRequest()))
        require(updated_detail["status"] == "approved", "application read-after-status-update failed")
        print("PASS postgres application status update")

        tbgn_date = date.today() + timedelta(days=60)
        tbgn_create = await main.admin_create_tbgn_project(
            FakeRequest(
                {
                    "name": "Phase 8D test TBGN",
                    "start_date": tbgn_date.isoformat(),
                    "end_date": (tbgn_date + timedelta(days=1)).isoformat(),
                    "affected_lines": "1",
                    "color": "#7c3aed",
                    "geometry": {"type": "Point", "coordinates": [4.9, 52.37]},
                    "status": "draft",
                    "notes": "temporary",
                }
            )
        )
        tbgn_project = response_json(tbgn_create)["project"]
        tbgn_id = tbgn_project["id"]
        require(tbgn_project["name"] == "Phase 8D test TBGN", "TBGN create failed")
        tbgn_update = await main.admin_update_tbgn_project(
            tbgn_id,
            FakeRequest({"status": "published", "notes": "temporary updated"}),
        )
        require(response_json(tbgn_update)["project"]["status"] == "published", "TBGN update failed")
        tbgn_delete = await main.admin_delete_tbgn_project(tbgn_id, FakeRequest())
        require(response_json(tbgn_delete)["ok"] is True, "TBGN delete failed")
        tbgn_id = None
        print("PASS postgres TBGN create/update/delete")

        stop_pair = first_transfer_stops()
        if stop_pair:
            main._build_rail_graph()
            transfer_date = date.today() + timedelta(days=45)
            transfer_response = await main.api_transfer_apply(
                FakeRequest(
                    {
                        "start_stop_id": stop_pair[0],
                        "end_stop_id": stop_pair[1],
                        "planned_date": transfer_date.isoformat(),
                        "planned_start_time": "10:00",
                        "planned_end_time": "11:00",
                        "tram_number": "phase8d",
                        "reason": "test",
                        "notes": "temporary transfer test",
                    }
                )
            )
            transfer_trip_id = response_json(transfer_response)["transfer_trip_id"]
            require(transfer_trip_id, "transfer trip create failed")
            transfer_status = await main.admin_update_transfer_trip_status(
                transfer_trip_id,
                FakeRequest(
                    {
                        "status": "approved",
                        "admin_note": "phase8d transfer approved",
                        "decision_message": "phase8d transfer decision",
                    }
                ),
            )
            require(response_json(transfer_status)["status"] == "approved", "transfer status update failed")
            transfer_delete = await main.admin_delete_transfer_trip(transfer_trip_id, FakeRequest())
            require(response_json(transfer_delete)["ok"] is True, "transfer delete failed")
            transfer_trip_id = None
            print("PASS postgres transfer create/status/delete")
        else:
            print("WARN no transfer stops available; skipped transfer write route test")

        delete_response = await main.admin_delete_application(application_id, FakeRequest())
        require(response_json(delete_response)["ok"] is True, "application delete failed")
        application_id = None
        print("PASS postgres application delete")
    except HTTPException as exc:
        raise AssertionError(f"route returned HTTP {exc.status_code}: {exc.detail}") from exc
    finally:
        main._require_user = original_require_user
        main._require_admin = original_require_admin
        cleanup_rows(application_id, transfer_trip_id, tbgn_id)
        if original_backend is None:
            os.environ.pop("APP_DB_BACKEND", None)
        else:
            os.environ["APP_DB_BACKEND"] = original_backend


def main_script() -> int:
    parser = argparse.ArgumentParser(description="Exercise APP_DB_BACKEND=postgres write routes locally.")
    parser.add_argument(
        "--allow-nonlocal",
        action="store_true",
        help="Allow running against a DATABASE_URL that is not localhost/127.0.0.1.",
    )
    args = parser.parse_args()
    local_database_url_required(allow_nonlocal=args.allow_nonlocal)
    asyncio.run(run_checks())
    return 0


if __name__ == "__main__":
    raise SystemExit(main_script())
