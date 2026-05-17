from __future__ import annotations

import sys
from typing import Any

from backend.audit_logs import write_audit_log
from backend.wior_refresh_job import run_wior_refresh_job
from scripts.sync_wior_to_postgis import sync_wior_to_postgis


def _sync_summary(sync_result: dict[str, Any]) -> dict[str, Any]:
    counts = sync_result.get("postgis_counts") or {}
    return {
        "ok": sync_result.get("ok"),
        "skipped": sync_result.get("skipped", False),
        "source_serving_rows": sync_result.get("source_serving_rows"),
        "rows_upserted": sync_result.get("rows_upserted"),
        "wior_sqlite_serving_rows": counts.get("wior_sqlite_serving_rows"),
        "latest_extent": counts.get("wior_work_areas_extent"),
    }


def run_wior_refresh_and_sync_job() -> dict[str, Any]:
    try:
        refresh_result = run_wior_refresh_job()
    except Exception as exc:
        write_audit_log(
            actor_email=None,
            actor_type="system",
            action_scope="system_action",
            action="wior_refresh_and_sync_failed",
            entity_type="wior_refresh",
            metadata={
                "failure_stage": "wior_refresh",
                "error_type": type(exc).__name__,
                "error": str(exc),
            },
        )
        raise

    if not refresh_result.get("ok"):
        write_audit_log(
            actor_email=None,
            actor_type="system",
            action_scope="system_action",
            action="wior_refresh_and_sync_failed",
            entity_type="wior_refresh",
            metadata={
                "failure_stage": "wior_refresh",
                "refresh_result": refresh_result,
            },
        )
        return {
            "ok": False,
            "wior_refresh": refresh_result,
            "postgis_sync": {
                "ok": False,
                "skipped": True,
                "skip_reason": "wior_refresh_not_successful",
            },
        }

    try:
        sync_result = sync_wior_to_postgis(apply=True, dry_run=False)
    except Exception as exc:
        write_audit_log(
            actor_email=None,
            actor_type="system",
            action_scope="system_action",
            action="wior_refresh_and_sync_failed",
            entity_type="wior_refresh",
            metadata={
                "failure_stage": "postgis_sync",
                "error_type": type(exc).__name__,
                "error": str(exc),
            },
        )
        raise

    result = {
        "ok": bool(sync_result.get("ok")),
        "wior_refresh": refresh_result,
        "postgis_sync": sync_result,
    }
    write_audit_log(
        actor_email=None,
        actor_type="system",
        action_scope="system_action",
        action="wior_refresh_and_sync_completed",
        entity_type="wior_refresh",
        metadata={
            "records_fetched": refresh_result.get("records_fetched"),
            "records_loaded": refresh_result.get("records_loaded"),
            "serving_loaded": refresh_result.get("serving_loaded"),
            "rows_upserted": sync_result.get("rows_upserted"),
            "source_serving_rows": sync_result.get("source_serving_rows"),
        },
    )
    return result


def print_combined_result(result: dict[str, Any]) -> None:
    print("WIOR refresh result:", result.get("wior_refresh"))
    sync_result = result.get("postgis_sync") or {}
    if sync_result.get("skipped"):
        reason = sync_result.get("skip_reason") or "unknown"
        print(f"PostGIS WIOR sync skipped: {reason}.")
    else:
        print("PostGIS WIOR sync result:", _sync_summary(sync_result))
    print("Combined WIOR refresh + PostGIS sync result:", {"ok": result.get("ok")})


def main() -> int:
    try:
        result = run_wior_refresh_and_sync_job()
    except Exception as exc:
        print(f"Combined WIOR refresh + PostGIS sync failed: {exc}", file=sys.stderr)
        return 1

    print_combined_result(result)
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
