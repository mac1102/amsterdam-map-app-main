from __future__ import annotations

import os
import sys
from typing import Any

import psycopg


def connect() -> psycopg.Connection[Any]:
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        raise RuntimeError("DATABASE_URL is not set")
    return psycopg.connect(database_url)


def scalar(conn: psycopg.Connection[Any], sql: str) -> Any:
    row = conn.execute(sql).fetchone()
    if row is None:
        return None
    return row[0]


def print_count(conn: psycopg.Connection[Any], table_name: str) -> None:
    print(f"{table_name} count: {scalar(conn, f'SELECT COUNT(*) FROM {table_name}')}")


def print_bool_counts(conn: psycopg.Connection[Any], title: str, sql: str) -> None:
    print(title)
    for value, count in conn.execute(sql):
        print(f"{value}: {count}")


def main() -> int:
    try:
        with connect() as conn:
            print("PostGIS version:")
            print(scalar(conn, "SELECT postgis_full_version()"))
            print()

            for table_name in ("tram_lines", "tram_segments", "tram_stops"):
                print_count(conn, table_name)
            print(
                "total_tram_source_records: "
                f"{scalar(conn, 'SELECT COUNT(*) FROM tram_stops')}"
            )

            print()
            print(
                "invalid tram_segments geometries: "
                f"{scalar(conn, 'SELECT COUNT(*) FROM tram_segments WHERE NOT ST_IsValid(geom)')}"
            )
            print(
                "invalid tram_stops geometries: "
                f"{scalar(conn, 'SELECT COUNT(*) FROM tram_stops WHERE NOT ST_IsValid(geom)')}"
            )

            print()
            print(
                "tram_segments extent: "
                f"{scalar(conn, 'SELECT ST_AsText(ST_Extent(geom)) FROM tram_segments')}"
            )
            print(
                "tram_stops extent: "
                f"{scalar(conn, 'SELECT ST_AsText(ST_Extent(geom)) FROM tram_stops')}"
            )
            print(
                "wior_work_areas extent: "
                f"{scalar(conn, '''
                SELECT ST_AsText(ST_Extent(geom))
                FROM wior_work_areas
                WHERE source = 'wior_sqlite_serving'
                ''')}"
            )

            print()
            print("tram_segments by source:")
            for source, count in conn.execute(
                "SELECT source, COUNT(*) FROM tram_segments GROUP BY source ORDER BY source"
            ):
                print(f"{source}: {count}")

            print()
            print_bool_counts(
                conn,
                "tram_stops by is_current_frontend_visible:",
                """
                SELECT is_current_frontend_visible, COUNT(*)
                FROM tram_stops
                GROUP BY is_current_frontend_visible
                ORDER BY is_current_frontend_visible DESC
                """,
            )
            print_bool_counts(
                conn,
                "tram_stops by is_valid_tram_line_stop:",
                """
                SELECT is_valid_tram_line_stop, COUNT(*)
                FROM tram_stops
                GROUP BY is_valid_tram_line_stop
                ORDER BY is_valid_tram_line_stop DESC
                """,
            )

            print()
            print("raw_lijn_select counts for old frontend-hidden tram_stops:")
            for raw_lijn_select, count in conn.execute(
                """
                SELECT raw_lijn_select, COUNT(*)
                FROM tram_stops
                WHERE is_current_frontend_visible = false
                GROUP BY raw_lijn_select
                ORDER BY COUNT(*) DESC
                """
            ):
                print(f"{raw_lijn_select}: {count}")

            print()
            print("old frontend-hidden tram_stops:")
            for row in conn.execute(
                """
                SELECT
                    stop_id,
                    stop_name,
                    raw_lijn,
                    raw_lijn_select,
                    current_display_lijn,
                    current_display_lijn_select,
                    valid_tram_lijn,
                    valid_tram_lijn_select,
                    is_current_frontend_visible,
                    is_valid_tram_line_stop
                FROM tram_stops
                WHERE is_current_frontend_visible = false
                ORDER BY stop_name
                """
            ):
                print(row)

            print()
            print_count(conn, "wior_work_areas")
            print(
                "wior_sqlite_serving rows: "
                f"{scalar(conn, '''
                SELECT COUNT(*)
                FROM wior_work_areas
                WHERE source = 'wior_sqlite_serving'
                ''')}"
            )
            print(
                "invalid wior_work_areas geometries: "
                f"{scalar(conn, '''
                SELECT COUNT(*)
                FROM wior_work_areas
                WHERE source = 'wior_sqlite_serving'
                  AND geom IS NOT NULL
                  AND NOT ST_IsValid(geom)
                ''')}"
            )
            print(
                "empty wior_work_areas geometries: "
                f"{scalar(conn, '''
                SELECT COUNT(*)
                FROM wior_work_areas
                WHERE source = 'wior_sqlite_serving'
                  AND (geom IS NULL OR ST_IsEmpty(geom))
                ''')}"
            )

            return 0
    except Exception as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
