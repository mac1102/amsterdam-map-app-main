from __future__ import annotations

import os
from typing import Any, Dict


def get_database_url() -> str:
    return os.getenv("DATABASE_URL", "").strip()


def check_postgres_health() -> Dict[str, Any]:
    database_url = get_database_url()
    if not database_url:
        return {
            "status": "not_configured",
            "configured": False,
        }

    try:
        import psycopg
    except ImportError:
        return {
            "status": "unavailable",
            "configured": True,
            "error": "psycopg is not installed",
        }

    try:
        with psycopg.connect(database_url, connect_timeout=3) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT
                        current_database(),
                        current_user,
                        EXISTS (
                            SELECT 1
                            FROM pg_extension
                            WHERE extname = 'postgis'
                        )
                    """
                )
                database_name, current_user, has_postgis = cur.fetchone()
    except Exception as exc:
        return {
            "status": "error",
            "configured": True,
            "error": str(exc),
        }

    return {
        "status": "ok",
        "configured": True,
        "database": database_name,
        "user": current_user,
        "postgis_enabled": bool(has_postgis),
    }
