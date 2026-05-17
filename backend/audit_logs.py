from __future__ import annotations

import os
from datetime import date, datetime
from typing import Any

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb


SENSITIVE_KEYS = {
    "password",
    "password_hash",
    "passwordhash",
    "hash",
    "payload_json",
    "source_payload_json",
    "file_content",
    "contents",
    "content",
    "raw_body",
    "request_body",
}

ACTION_SUMMARIES = {
    "login_success": "Logged in",
    "login_failed": "Login failed",
    "application_submitted": "Submitted an application",
    "file_upload_metadata_saved": "Saved file upload metadata",
    "transfer_trip_submitted": "Submitted a transfer trip",
    "application_status_changed": "Changed application status",
    "application_deleted": "Deleted an application",
    "transfer_trip_status_changed": "Changed transfer trip status",
    "transfer_trip_deleted": "Deleted a transfer trip",
    "tbgn_project_created": "Created a TBGN project",
    "tbgn_project_updated": "Updated a TBGN project",
    "tbgn_project_deleted": "Deleted a TBGN project",
    "wior_conflict_checked": "Checked WIOR conflicts",
    "wior_postgis_fallback_to_legacy": "WIOR check fell back to legacy",
    "wior_refresh_and_sync_completed": "Completed WIOR refresh and PostGIS sync",
    "wior_refresh_and_sync_failed": "WIOR refresh and PostGIS sync failed",
}


def get_database_url() -> str:
    return os.getenv("DATABASE_URL", "").strip()


def connect() -> psycopg.Connection[dict[str, Any]]:
    database_url = get_database_url()
    if not database_url:
        raise RuntimeError("DATABASE_URL is not set")
    return psycopg.connect(database_url, row_factory=dict_row)


def _iso(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    return value


def _safe_string(value: str, max_len: int = 500) -> str:
    if len(value) <= max_len:
        return value
    return value[:max_len] + "...[truncated]"


def sanitize_audit_value(value: Any, depth: int = 0) -> Any:
    if value is None:
        return None
    if depth > 4:
        return "[truncated]"
    if isinstance(value, dict):
        sanitized: dict[str, Any] = {}
        for key, item in value.items():
            key_text = str(key)
            if key_text.lower() in SENSITIVE_KEYS:
                continue
            sanitized[key_text] = sanitize_audit_value(item, depth + 1)
        return sanitized
    if isinstance(value, (list, tuple)):
        return [sanitize_audit_value(item, depth + 1) for item in list(value)[:50]]
    if isinstance(value, bytes):
        return "[bytes omitted]"
    if isinstance(value, str):
        return _safe_string(value)
    if isinstance(value, (datetime, date)):
        return _iso(value)
    if isinstance(value, (bool, int, float)):
        return value
    return _safe_string(str(value))


def _request_ip(request: Any) -> str | None:
    if request is None:
        return None
    client = getattr(request, "client", None)
    host = getattr(client, "host", None)
    return str(host) if host else None


def _request_user_agent(request: Any) -> str | None:
    if request is None:
        return None
    headers = getattr(request, "headers", None)
    if not headers:
        return None
    value = headers.get("user-agent")
    return _safe_string(str(value), max_len=300) if value else None


def write_audit_log(
    actor_email: str | None,
    actor_type: str,
    action_scope: str,
    action: str,
    entity_type: str | None = None,
    entity_id: str | None = None,
    old_value: dict | None = None,
    new_value: dict | None = None,
    metadata: dict | None = None,
    request: Any = None,
    conn: psycopg.Connection[dict[str, Any]] | None = None,
) -> None:
    if conn is None and not get_database_url():
        return

    actor_email = str(actor_email or "").strip().lower() or None
    actor_type = str(actor_type or "unknown").strip().lower() or "unknown"
    action_scope = str(action_scope or "system_action").strip().lower() or "system_action"
    action = str(action or "").strip().lower()
    if not action:
        return

    params = (
        actor_email,
        actor_type,
        action_scope,
        action,
        str(entity_type or "").strip() or None,
        str(entity_id or "").strip() or None,
        Jsonb(sanitize_audit_value(old_value)) if old_value is not None else None,
        Jsonb(sanitize_audit_value(new_value)) if new_value is not None else None,
        Jsonb(sanitize_audit_value(metadata)) if metadata is not None else None,
        _request_ip(request),
        _request_user_agent(request),
    )
    sql = """
        INSERT INTO audit_logs (
            actor_email,
            actor_type,
            action_scope,
            action,
            entity_type,
            entity_id,
            old_value,
            new_value,
            metadata,
            ip_address,
            user_agent
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
    """

    try:
        if conn is not None:
            with conn.transaction():
                conn.execute(sql, params)
            return
        with connect() as owned_conn:
            with owned_conn.transaction():
                owned_conn.execute(sql, params)
    except Exception:
        # Audit logging should never make SQLite fallback or runtime actions fail.
        return


def _activity_row(row: dict[str, Any]) -> dict[str, Any]:
    metadata = sanitize_audit_value(row.get("metadata") or {})
    return {
        "id": row.get("id"),
        "created_at": _iso(row.get("created_at")),
        "actor_email": row.get("actor_email"),
        "actor_type": row.get("actor_type"),
        "action": row.get("action"),
        "action_scope": row.get("action_scope"),
        "entity_type": row.get("entity_type"),
        "entity_id": row.get("entity_id"),
        "summary": ACTION_SUMMARIES.get(str(row.get("action") or ""), str(row.get("action") or "")),
        "metadata": metadata if isinstance(metadata, dict) else {},
    }


def list_user_activity(
    actor_email: str,
    limit: int = 50,
    offset: int = 0,
    action_scope: str | None = None,
) -> list[dict[str, Any]]:
    if not get_database_url():
        return []
    safe_limit = max(1, min(int(limit or 50), 200))
    safe_offset = max(0, int(offset or 0))
    email = str(actor_email or "").strip().lower()
    params: list[Any] = [email]
    sql = """
        SELECT id, created_at, actor_email, actor_type, action_scope, action,
               entity_type, entity_id, metadata
        FROM audit_logs
        WHERE lower(actor_email) = %s
    """
    if action_scope:
        sql += " AND action_scope = %s"
        params.append(str(action_scope).strip())
    sql += " ORDER BY created_at DESC, id DESC LIMIT %s OFFSET %s"
    params.extend([safe_limit, safe_offset])

    with connect() as conn:
        rows = conn.execute(sql, tuple(params)).fetchall()
    return [_activity_row(row) for row in rows]


def list_admin_audit_logs(
    actor_email: str | None = None,
    action_scope: str | None = None,
    entity_type: str | None = None,
    entity_id: str | None = None,
    limit: int = 100,
    offset: int = 0,
) -> list[dict[str, Any]]:
    if not get_database_url():
        return []
    safe_limit = max(1, min(int(limit or 100), 500))
    safe_offset = max(0, int(offset or 0))
    filters: list[str] = []
    params: list[Any] = []
    if actor_email:
        filters.append("lower(actor_email) = %s")
        params.append(str(actor_email).strip().lower())
    if action_scope:
        filters.append("action_scope = %s")
        params.append(str(action_scope).strip())
    if entity_type:
        filters.append("entity_type = %s")
        params.append(str(entity_type).strip())
    if entity_id:
        filters.append("entity_id = %s")
        params.append(str(entity_id).strip())

    where_sql = f"WHERE {' AND '.join(filters)}" if filters else ""
    sql = f"""
        SELECT id, created_at, actor_email, actor_type, action_scope, action,
               entity_type, entity_id, metadata
        FROM audit_logs
        {where_sql}
        ORDER BY created_at DESC, id DESC
        LIMIT %s OFFSET %s
    """
    params.extend([safe_limit, safe_offset])

    with connect() as conn:
        rows = conn.execute(sql, tuple(params)).fetchall()
    return [_activity_row(row) for row in rows]
