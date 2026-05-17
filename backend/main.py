from __future__ import annotations

import base64
import hashlib
import heapq
import hmac
import io
import json
import math
import os
import re
import secrets
import threading
import time
import sqlite3
import uuid
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from functools import lru_cache
from pathlib import Path
from pydantic import BaseModel
from typing import Any, Dict, List, Optional, Tuple

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass  # python-dotenv optional; use real env vars in production
from fastapi import HTTPException, Response

from backend.wior_fetch import (
    init_wior_db,
    sync_wior_data,
    get_cached_wior_serving_features,
    get_cached_wior_features,
)

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.openapi.docs import get_swagger_ui_html
from fastapi.openapi.utils import get_openapi
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware

from backend.audit_logs import list_admin_audit_logs, list_user_activity, write_audit_log
from backend.db_postgres import check_postgres_health
from backend.feature_index import FeatureIndex
from backend.postgres_app_queries import PostgresAppQueries
from backend.postgis_queries import find_nearest_segment_postgis, is_postgis_click_available
from backend.postgis_wior_queries import (
    find_wior_conflicts_postgis,
    get_postgis_wior_mirror_status,
)
from backend.tile_server import TileServer

ROOT = Path(__file__).resolve().parents[1]
STATIC_DIR = ROOT / "static"
DATA_DIR = ROOT / "backend" / "data"

MAP_PATH = DATA_DIR / "map.png"
FEATURES_PATH = DATA_DIR / "features.json"

UPLOADS_DIR = DATA_DIR / "uploads"
DB_PATH = DATA_DIR / "app.db"

UPLOADS_DIR.mkdir(parents=True, exist_ok=True)


def _env_flag(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _app_db_backend() -> str:
    raw = os.getenv("APP_DB_BACKEND", "sqlite").strip().lower()
    if raw == "postgres":
        return "postgres"
    return "sqlite"


def _use_postgres_read_backend() -> bool:
    return _app_db_backend() == "postgres"


def _audit_runtime_enabled() -> bool:
    return _use_postgres_read_backend()


FEATURE_FLAGGED_READ_ROUTE_PATHS = [
    "GET /api/line_status",
    "GET /api/my_applications",
    "GET /api/admin/applications",
    "GET /api/admin/applications/{application_id}",
    "GET /api/tbgn/projects",
    "GET /api/admin/tbgn",
    "GET /api/admin/tbgn/{project_id}",
    "GET /api/segment_bookings",
    "GET /api/my_transfer_trips",
    "GET /api/admin/transfer_trips",
    "GET /api/admin/transfer_trips/{trip_id}",
]


def _postgres_read_unavailable(exc: Exception) -> HTTPException:
    return HTTPException(
        status_code=503,
        detail=f"PostgreSQL read backend unavailable: {exc}",
    )


class ProtectedStaticFiles(StaticFiles):
    async def get_response(self, path: str, scope) -> Response:
        normalized = path.replace("\\", "/").lstrip("/")
        if normalized.startswith("data/"):
            raise HTTPException(status_code=404, detail="Not found.")
        return await super().get_response(path, scope)

app = FastAPI(
    title="GVB Tram communication map",
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
)
app.mount("/static", ProtectedStaticFiles(directory=str(STATIC_DIR)), name="static")

SESSION_SECRET = os.getenv("SESSION_SECRET", "").strip()
if not SESSION_SECRET:
    raise RuntimeError(
        "SESSION_SECRET environment variable is not set. "
        "Add it to your .env file or set it in your environment before starting the server."
    )

SESSION_HTTPS_ONLY = _env_flag("SESSION_HTTPS_ONLY", default=False)
BOOTSTRAP_RESET_EXISTING_USERS = _env_flag("BOOTSTRAP_RESET_EXISTING_USERS", default=False)
WIOR_AUTO_REFRESH_ENABLED = _env_flag("WIOR_AUTO_REFRESH_ENABLED", default=True)

app.add_middleware(
    SessionMiddleware,
    secret_key=SESSION_SECRET,
    same_site="lax",
    https_only=SESSION_HTTPS_ONLY,
    max_age=60 * 60 * 4,
)

ADMIN_EMAIL = os.getenv("ADMIN_EMAIL", "").strip().lower()
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "").strip()
SEED_USER_EMAIL = os.getenv("SEED_USER_EMAIL", "").strip().lower()
SEED_USER_PASSWORD = os.getenv("SEED_USER_PASSWORD", "").strip()


MAX_FILE_SIZE_BYTES = 10 * 1024 * 1024
MAX_UPLOAD_FILES = 10
ALLOWED_EXTENSIONS = {".pdf", ".doc", ".docx", ".png", ".jpg", ".jpeg"}
GENERIC_CONTENT_TYPES = {"", "application/octet-stream"}
ALLOWED_CONTENT_TYPES = {
    ".pdf": {"application/pdf"},
    ".doc": {
        "application/msword",
        "application/doc",
        "application/vnd.ms-word",
        "application/x-msword",
    },
    ".docx": {
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "application/zip",
        "application/x-zip-compressed",
    },
    ".png": {"image/png"},
    ".jpg": {"image/jpeg", "image/pjpeg"},
    ".jpeg": {"image/jpeg", "image/pjpeg"},
}
PROTOTYPE_DATA_FILES = {
    "spoor_data": (STATIC_DIR / "data" / "spoor_data.js", "SPOOR_DATA"),
    "spoortakken_data": (STATIC_DIR / "data" / "spoortakken_data.js", "SPOORTAKKEN_DATA"),
    "bovenleiding_data": (STATIC_DIR / "data" / "bovenleiding_data.js", "BOVENLEIDING_DATA"),
    "haltes_data": (STATIC_DIR / "data" / "haltes_data.js", "HALTES_DATA"),
}
HALTES_TRAM_CODES = {
    "01", "02", "04", "05", "06", "07",
    "12", "13", "14", "17", "19",
    "24", "25", "26", "27",
}
LOGIN_RATE_LIMIT_WINDOW_SECONDS = 15 * 60
LOGIN_RATE_LIMIT_MAX_FAILURES = 10
LOGIN_FAILURES: Dict[str, List[float]] = {}
DUTCH_WEEKDAY_SHORT = ["ma", "di", "wo", "do", "vr", "za", "zo"]

tile_server = TileServer(MAP_PATH, tile_size=256)
feature_index = FeatureIndex(FEATURES_PATH)


# -------------------- database helpers --------------------
def get_db() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db() -> None:
    with get_db() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS users (
                email TEXT PRIMARY KEY,
                password_hash TEXT NOT NULL,
                created_at TEXT NOT NULL,
                is_admin INTEGER NOT NULL DEFAULT 0
            );

            CREATE TABLE IF NOT EXISTS applications (
                application_id TEXT PRIMARY KEY,
                submitted_at TEXT NOT NULL,
                status TEXT NOT NULL,
                submitted_by_email TEXT NOT NULL,
                person_mode TEXT NOT NULL,
                work_description TEXT,
                work_source TEXT,
                urgency TEXT,
                affected_lines TEXT,
                work_notes TEXT,
                coordinator TEXT,
                vvw_measure TEXT,
                FOREIGN KEY(submitted_by_email) REFERENCES users(email) ON DELETE CASCADE
            );

            CREATE INDEX IF NOT EXISTS idx_applications_email
            ON applications(submitted_by_email);

            CREATE TABLE IF NOT EXISTS application_targets (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                application_id TEXT NOT NULL,
                target_index INTEGER NOT NULL,
                target_type TEXT DEFAULT 'rail_segment',
                asset_id TEXT,
                asset_label TEXT,
                asset_source TEXT,
                segment_id TEXT,
                line_id TEXT,
                line_name TEXT,
                work_mode TEXT NOT NULL,
                work_start_x INTEGER,
                work_start_y INTEGER,
                work_end_x INTEGER,
                work_end_y INTEGER,
                project_start TEXT NOT NULL,
                project_end TEXT NOT NULL,
                FOREIGN KEY(application_id) REFERENCES applications(application_id) ON DELETE CASCADE
            );

            CREATE INDEX IF NOT EXISTS idx_targets_application
            ON application_targets(application_id);

            CREATE TABLE IF NOT EXISTS application_target_windows (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                target_id INTEGER NOT NULL,
                window_index INTEGER NOT NULL,
                project_start TEXT NOT NULL,
                project_end TEXT NOT NULL,
                label TEXT,
                FOREIGN KEY(target_id) REFERENCES application_targets(id) ON DELETE CASCADE
            );

            CREATE INDEX IF NOT EXISTS idx_target_windows_target
            ON application_target_windows(target_id);

            CREATE TABLE IF NOT EXISTS application_people (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                application_id TEXT NOT NULL,
                target_index INTEGER,
                first_name TEXT NOT NULL,
                last_name TEXT NOT NULL,
                phone TEXT NOT NULL,
                email TEXT NOT NULL,
                employee_id TEXT,
                FOREIGN KEY(application_id) REFERENCES applications(application_id) ON DELETE CASCADE
            );

            CREATE INDEX IF NOT EXISTS idx_people_application
            ON application_people(application_id);

            CREATE TABLE IF NOT EXISTS application_uploads (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                application_id TEXT NOT NULL,
                original_filename TEXT NOT NULL,
                stored_filename TEXT NOT NULL,
                created_at TEXT NOT NULL,
                FOREIGN KEY(application_id) REFERENCES applications(application_id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS transfer_trips (
                transfer_trip_id TEXT PRIMARY KEY,
                submitted_at TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'submitted',
                submitted_by_email TEXT NOT NULL,
                start_stop_id INTEGER NOT NULL,
                start_stop_name TEXT NOT NULL,
                end_stop_id INTEGER NOT NULL,
                end_stop_name TEXT NOT NULL,
                planned_date TEXT NOT NULL,
                planned_start_time TEXT NOT NULL,
                planned_end_time TEXT NOT NULL,
                tram_number TEXT,
                reason TEXT,
                notes TEXT,
                route_distance_m REAL,
                route_geometry TEXT,
                admin_note TEXT DEFAULT '',
                decision_message TEXT DEFAULT '',
                FOREIGN KEY(submitted_by_email) REFERENCES users(email) ON DELETE CASCADE
            );

            CREATE INDEX IF NOT EXISTS idx_transfer_trips_email
            ON transfer_trips(submitted_by_email);

            CREATE TABLE IF NOT EXISTS transfer_trip_points (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                transfer_trip_id TEXT NOT NULL,
                point_index INTEGER NOT NULL,
                segment_id TEXT,
                lng REAL NOT NULL,
                lat REAL NOT NULL,
                FOREIGN KEY(transfer_trip_id) REFERENCES transfer_trips(transfer_trip_id) ON DELETE CASCADE
            );

            CREATE INDEX IF NOT EXISTS idx_transfer_trip_points_trip
            ON transfer_trip_points(transfer_trip_id);

            CREATE TABLE IF NOT EXISTS tbgn_projects (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                start_date TEXT NOT NULL,
                end_date TEXT NOT NULL,
                affected_lines TEXT,
                color TEXT DEFAULT '#7c3aed',
                geometry TEXT,
                status TEXT NOT NULL DEFAULT 'draft',
                notes TEXT,
                created_by TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_tbgn_projects_status_dates
            ON tbgn_projects(status, start_date, end_date);
            """
        )


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 200_000)
    return f"pbkdf2_sha256$200000${base64.b64encode(salt).decode()}${base64.b64encode(digest).decode()}"


def verify_password(password: str, stored_hash: str) -> bool:
    try:
        algo, iterations, salt_b64, digest_b64 = stored_hash.split("$", 3)
        if algo != "pbkdf2_sha256":
            return False
        salt = base64.b64decode(salt_b64)
        expected = base64.b64decode(digest_b64)
        actual = hashlib.pbkdf2_hmac(
            "sha256",
            password.encode("utf-8"),
            salt,
            int(iterations),
        )
        return hmac.compare_digest(actual, expected)
    except Exception:
        return False

def _ensure_application_admin_fields(conn):
    cols = {
        row["name"]
        for row in conn.execute("PRAGMA table_info(applications)").fetchall()
    }

    if "admin_note" not in cols:
        conn.execute("ALTER TABLE applications ADD COLUMN admin_note TEXT")

    if "decision_message" not in cols:
        conn.execute("ALTER TABLE applications ADD COLUMN decision_message TEXT")

    optional_text_columns = [
        "work_description",
        "work_source",
        "urgency",
        "affected_lines",
        "work_notes",
        "coordinator",
        "vvw_measure",
    ]
    for col in optional_text_columns:
        if col not in cols:
            conn.execute(f"ALTER TABLE applications ADD COLUMN {col} TEXT")

    conn.commit()

VALID_APPLICATION_TARGET_TYPES = {"rail_segment", "switch_junction", "overhead_section"}


def _ensure_application_target_asset_fields(conn):
    cols = {
        row["name"]
        for row in conn.execute("PRAGMA table_info(application_targets)").fetchall()
    }

    if "target_type" not in cols:
        conn.execute("ALTER TABLE application_targets ADD COLUMN target_type TEXT DEFAULT 'rail_segment'")
    if "asset_id" not in cols:
        conn.execute("ALTER TABLE application_targets ADD COLUMN asset_id TEXT")
    if "asset_label" not in cols:
        conn.execute("ALTER TABLE application_targets ADD COLUMN asset_label TEXT")
    if "asset_source" not in cols:
        conn.execute("ALTER TABLE application_targets ADD COLUMN asset_source TEXT")

    conn.execute(
        """
        UPDATE application_targets
        SET target_type = 'rail_segment'
        WHERE target_type IS NULL OR trim(target_type) = ''
        """
    )
    conn.execute(
        """
        UPDATE application_targets
        SET asset_id = segment_id
        WHERE (asset_id IS NULL OR trim(asset_id) = '')
          AND segment_id IS NOT NULL
          AND trim(segment_id) != ''
        """
    )
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_targets_asset_time
        ON application_targets(target_type, asset_id, project_start, project_end)
        """
    )
    conn.commit()

def ensure_admin_user() -> None:
    if not ADMIN_EMAIL or not ADMIN_PASSWORD:
        return

    now = datetime.now(timezone.utc).isoformat()

    with get_db() as conn:
        existing = conn.execute(
            "SELECT email FROM users WHERE email = ?",
            (ADMIN_EMAIL,),
        ).fetchone()

        if existing:
            if BOOTSTRAP_RESET_EXISTING_USERS:
                pw_hash = hash_password(ADMIN_PASSWORD)
                conn.execute(
                    """
                    UPDATE users
                    SET password_hash = ?, is_admin = 1
                    WHERE email = ?
                    """,
                    (pw_hash, ADMIN_EMAIL),
                )
            else:
                conn.execute(
                    """
                    UPDATE users
                    SET is_admin = 1
                    WHERE email = ?
                    """,
                    (ADMIN_EMAIL,),
                )
        else:
            pw_hash = hash_password(ADMIN_PASSWORD)
            conn.execute(
                """
                INSERT INTO users (email, password_hash, created_at, is_admin)
                VALUES (?, ?, ?, 1)
                """,
                (ADMIN_EMAIL, pw_hash, now),
            )

def ensure_seed_user() -> None:
    if not SEED_USER_EMAIL or not SEED_USER_PASSWORD:
        return

    now = datetime.now(timezone.utc).isoformat()

    with get_db() as conn:
        existing = conn.execute(
            "SELECT email FROM users WHERE email = ?",
            (SEED_USER_EMAIL,),
        ).fetchone()

        if existing:
            if BOOTSTRAP_RESET_EXISTING_USERS:
                pw_hash = hash_password(SEED_USER_PASSWORD)
                conn.execute(
                    """
                    UPDATE users
                    SET password_hash = ?, is_admin = 0
                    WHERE email = ?
                    """,
                    (pw_hash, SEED_USER_EMAIL),
                )
            else:
                conn.execute(
                    """
                    UPDATE users
                    SET is_admin = 0
                    WHERE email = ?
                    """,
                    (SEED_USER_EMAIL,),
                )
        else:
            pw_hash = hash_password(SEED_USER_PASSWORD)
            conn.execute(
                """
                INSERT INTO users (email, password_hash, created_at, is_admin)
                VALUES (?, ?, ?, 0)
                """,
                (SEED_USER_EMAIL, pw_hash, now),
            )


WIOR_REFRESH_INTERVAL_SECONDS = 60 * 60  # 1 hour


def _run_wior_refresh_job() -> None:
    try:
        result = sync_wior_data()
        print("WIOR refresh result:", result)
    except Exception as exc:
        print("WIOR refresh failed:", exc)


def _wior_refresh_loop() -> None:
    while True:
        time.sleep(WIOR_REFRESH_INTERVAL_SECONDS)
        _run_wior_refresh_job()


@app.on_event("startup")
def startup() -> None:
    init_db()
    init_wior_db()

    with get_db() as conn:
        _ensure_application_admin_fields(conn)
        _ensure_application_target_asset_fields(conn)

    ensure_admin_user()
    ensure_seed_user()
    _build_rail_graph()

    if WIOR_AUTO_REFRESH_ENABLED and not getattr(app.state, "wior_refresh_thread_started", False):
        thread = threading.Thread(
            target=_wior_refresh_loop,
            name="wior-refresh",
            daemon=True,
        )
        thread.start()
        app.state.wior_refresh_thread_started = True


# -------------------- Rail graph for transfer trip routing --------------------
_RAIL_GRAPH: Dict[str, List[Tuple[str, float, str, List[List[float]]]]] = {}
_HALTES_SNAPPED: Dict[int, Dict[str, Any]] = {}


def _coord_key(lng: float, lat: float) -> str:
    return f"{round(lng, 6)},{round(lat, 6)}"


def _haversine_m(lng1: float, lat1: float, lng2: float, lat2: float) -> float:
    R = 6_371_000.0
    d_lat = math.radians(lat2 - lat1)
    d_lng = math.radians(lng2 - lng1)
    a = (
        math.sin(d_lat / 2) ** 2
        + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2))
        * math.sin(d_lng / 2) ** 2
    )
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def _build_rail_graph() -> None:
    global _RAIL_GRAPH, _HALTES_SNAPPED
    graph: Dict[str, List[Tuple[str, float, str, List[List[float]]]]] = defaultdict(list)

    try:
        spoor_data = _load_embedded_json_constant(
            str(STATIC_DIR / "data" / "spoor_data.js"), "SPOOR_DATA"
        )
    except Exception as exc:
        print(f"[transfer] WARNING: Could not load SPOOR_DATA for graph: {exc}")
        _RAIL_GRAPH = {}
        _HALTES_SNAPPED = {}
        return

    features = spoor_data.get("features") or []
    for feature in features:
        geom = feature.get("geometry") or {}
        geom_type = geom.get("type") or ""
        raw_coords = geom.get("coordinates") or []
        props = feature.get("properties") or {}
        seg_id = str(props.get("k") or "").strip()
        if not seg_id:
            continue

        # Handle MultiLineString by flattening
        if geom_type == "MultiLineString":
            coord_lists = raw_coords
        else:
            coord_lists = [raw_coords]

        for coords in coord_lists:
            if len(coords) < 2:
                continue

            # Validate that coords are [number, number, ...] not nested arrays
            valid_coords = []
            for c in coords:
                if isinstance(c, (list, tuple)) and len(c) >= 2:
                    if isinstance(c[0], (int, float)) and isinstance(c[1], (int, float)):
                        valid_coords.append(c)

            if len(valid_coords) < 2:
                continue

            for i in range(len(valid_coords) - 1):
                c0 = valid_coords[i]
                c1 = valid_coords[i + 1]

                k0 = _coord_key(c0[0], c0[1])
                k1 = _coord_key(c1[0], c1[1])
                dist = _haversine_m(c0[0], c0[1], c1[0], c1[1])

                graph[k0].append((k1, dist, seg_id, [c0[:2], c1[:2]]))
                graph[k1].append((k0, dist, seg_id, [c1[:2], c0[:2]]))

            if len(valid_coords) >= 2:
                first_key = _coord_key(valid_coords[0][0], valid_coords[0][1])
                last_key = _coord_key(valid_coords[-1][0], valid_coords[-1][1])
                total_dist = sum(
                    _haversine_m(
                        valid_coords[j][0], valid_coords[j][1],
                        valid_coords[j + 1][0], valid_coords[j + 1][1],
                    )
                    for j in range(len(valid_coords) - 1)
                )
                full_coords = [c[:2] for c in valid_coords]
                graph[first_key].append((last_key, total_dist, seg_id, full_coords))
                graph[last_key].append((first_key, total_dist, seg_id, list(reversed(full_coords))))

    _RAIL_GRAPH = dict(graph)
    print(f"[transfer] Rail graph built: {len(_RAIL_GRAPH)} nodes, "
          f"{sum(len(v) for v in _RAIL_GRAPH.values())} edges")

    try:
        haltes_data = _load_haltes_data(str(STATIC_DIR / "data" / "haltes_data.js"))
    except Exception as exc:
        print(f"[transfer] WARNING: Could not load HALTES_DATA for snapping: {exc}")
        _HALTES_SNAPPED = {}
        return

    snapped: Dict[int, Dict[str, Any]] = {}
    all_nodes = []
    for key in _RAIL_GRAPH:
        parts = key.split(",")
        all_nodes.append((float(parts[0]), float(parts[1]), key))

    for feature in (haltes_data.get("features") or []):
        fid = feature.get("id")
        if fid is None:
            continue
        props = feature.get("properties") or {}
        geom = feature.get("geometry") or {}
        coords = geom.get("coordinates") or []
        if len(coords) < 2:
            continue

        hlng, hlat = coords[0], coords[1]
        best_dist = float("inf")
        best_key = None

        for nlng, nlat, nkey in all_nodes:
            d = _haversine_m(hlng, hlat, nlng, nlat)
            if d < best_dist:
                best_dist = d
                best_key = nkey

        if best_key and best_dist < 500:
            snapped[int(fid)] = {
                "id": int(fid),
                "name": props.get("Naam") or props.get("Label") or f"Stop {fid}",
                "coordinates": [hlng, hlat],
                "graph_node": best_key,
                "snap_distance_m": round(best_dist, 1),
            }

    _HALTES_SNAPPED = snapped
    print(f"[transfer] Snapped {len(_HALTES_SNAPPED)} tram stops to graph nodes")


def _dijkstra(
    graph: Dict[str, List[Tuple[str, float, str, List[List[float]]]]],
    start: str,
    end: str,
) -> Optional[Tuple[float, List[str], List[str], List[List[float]]]]:
    if start not in graph or end not in graph:
        return None

    dist: Dict[str, float] = {start: 0.0}
    prev: Dict[str, Optional[Tuple[str, str, List[List[float]]]]] = {start: None}
    heap = [(0.0, start)]
    visited = set()

    while heap:
        d, node = heapq.heappop(heap)
        if node in visited:
            continue
        visited.add(node)

        if node == end:
            break

        for neighbor, weight, seg_id, edge_coords in graph.get(node, []):
            if neighbor in visited:
                continue
            new_dist = d + weight
            if new_dist < dist.get(neighbor, float("inf")):
                dist[neighbor] = new_dist
                prev[neighbor] = (node, seg_id, edge_coords)
                heapq.heappush(heap, (new_dist, neighbor))

    if end not in prev:
        return None

    path_nodes: List[str] = []
    segments: List[str] = []
    all_coords: List[List[float]] = []
    current = end

    while current is not None:
        path_nodes.append(current)
        entry = prev.get(current)
        if entry is None:
            break
        parent, seg_id, edge_coords = entry
        if seg_id:
            segments.append(seg_id)
        if edge_coords:
            reversed_coords = list(reversed(edge_coords))
            if all_coords:
                if reversed_coords[-1] == all_coords[0]:
                    all_coords = reversed_coords[:-1] + all_coords
                else:
                    all_coords = reversed_coords + all_coords
            else:
                all_coords = reversed_coords
        current = parent

    path_nodes.reverse()
    segments.reverse()
    unique_segments = list(dict.fromkeys(segments))

    return (dist[end], path_nodes, unique_segments, all_coords)


def _compute_transfer_route(
    start_stop_id: int, end_stop_id: int
) -> Dict[str, Any]:
    if not _RAIL_GRAPH:
        raise HTTPException(status_code=503, detail="Rail graph not available.")

    start_info = _HALTES_SNAPPED.get(start_stop_id)
    end_info = _HALTES_SNAPPED.get(end_stop_id)

    if not start_info:
        raise HTTPException(status_code=400, detail=f"Start stop ID {start_stop_id} not found.")
    if not end_info:
        raise HTTPException(status_code=400, detail=f"End stop ID {end_stop_id} not found.")

    if start_stop_id == end_stop_id:
        raise HTTPException(status_code=400, detail="Start and end stops must be different.")

    result = _dijkstra(_RAIL_GRAPH, start_info["graph_node"], end_info["graph_node"])
    if result is None:
        raise HTTPException(
            status_code=404,
            detail="No route found between the selected stops.",
        )

    total_distance, path_nodes, segments, route_coords = result

    return {
        "start_stop": {
            "id": start_info["id"],
            "name": start_info["name"],
            "coordinates": start_info["coordinates"],
        },
        "end_stop": {
            "id": end_info["id"],
            "name": end_info["name"],
            "coordinates": end_info["coordinates"],
        },
        "segments": segments,
        "geometry": {
            "type": "LineString",
            "coordinates": route_coords,
        },
        "distance_m": round(total_distance, 1),
    }


# -------------------- helpers --------------------
def _safe_name(name: str) -> str:
    keep = "._-() "
    out = "".join(c for c in name if c.isalnum() or c in keep).strip()
    return out or "upload.bin"


def _parse_iso_date_safe(value: str) -> Optional[date]:
    try:
        return date.fromisoformat(value)
    except (ValueError, TypeError):
        return None


def _get_user(request: Request) -> Optional[Dict[str, Any]]:
    return request.session.get("user")


def _require_user(request: Request) -> Dict[str, Any]:
    user = _get_user(request)
    if not user:
        raise HTTPException(status_code=401, detail="Not logged in.")
    return user

def _require_admin(request: Request) -> Dict[str, Any]:
    user = _require_user(request)
    if not bool(user.get("is_admin")):
        raise HTTPException(status_code=403, detail="Admin access required.")
    return user


TBGN_ALLOWED_STATUSES = {"draft", "published"}
TBGN_DEFAULT_COLOR = "#7c3aed"
TBGN_COLOR_RE = re.compile(r"^#[0-9a-fA-F]{6}$")
TBGN_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
TBGN_GEOMETRY_TYPES = {
    "Point",
    "MultiPoint",
    "LineString",
    "MultiLineString",
    "Polygon",
    "MultiPolygon",
    "GeometryCollection",
}


def _normalize_tbgn_color(value: Any) -> str:
    color = str(value or "").strip()
    if TBGN_COLOR_RE.match(color):
        return color.lower()
    return TBGN_DEFAULT_COLOR


def _parse_tbgn_date(value: Any, field_name: str) -> date:
    raw = str(value or "").strip()
    if not TBGN_DATE_RE.match(raw):
        raise HTTPException(status_code=400, detail=f"{field_name} must be YYYY-MM-DD.")
    parsed = _parse_iso_date_safe(raw)
    if not parsed:
        raise HTTPException(status_code=400, detail=f"{field_name} must be a valid date.")
    return parsed


def _geojson_position_valid(value: Any) -> bool:
    return (
        isinstance(value, list)
        and len(value) >= 2
        and all(isinstance(coord, (int, float)) and not isinstance(coord, bool) for coord in value[:2])
    )


def _geojson_coordinates_valid(value: Any) -> bool:
    if _geojson_position_valid(value):
        return True
    return isinstance(value, list) and bool(value) and all(_geojson_coordinates_valid(item) for item in value)


def _geojson_object_valid(value: Any) -> bool:
    if not isinstance(value, dict):
        return False

    geo_type = value.get("type")
    if geo_type == "Feature":
        geometry = value.get("geometry")
        return geometry is None or _geojson_object_valid(geometry)

    if geo_type == "FeatureCollection":
        features = value.get("features")
        return isinstance(features, list) and all(_geojson_object_valid(feature) for feature in features)

    if geo_type == "GeometryCollection":
        geometries = value.get("geometries")
        return isinstance(geometries, list) and all(_geojson_object_valid(geometry) for geometry in geometries)

    if geo_type in TBGN_GEOMETRY_TYPES:
        return _geojson_coordinates_valid(value.get("coordinates"))

    return False


def _normalize_tbgn_geometry(value: Any) -> tuple[Optional[str], Optional[Any]]:
    if value is None:
        return None, None

    if isinstance(value, str):
        raw = value.strip()
        if not raw:
            return None, None
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            raise HTTPException(status_code=400, detail="geometry must be valid JSON.")
    else:
        parsed = value

    if not _geojson_object_valid(parsed):
        raise HTTPException(status_code=400, detail="geometry must be valid-ish GeoJSON.")

    return json.dumps(parsed, separators=(",", ":"), ensure_ascii=False), parsed


def _validate_tbgn_payload(body: Dict[str, Any], existing: Optional[sqlite3.Row] = None) -> Dict[str, Any]:
    def get_value(key: str, default: Any = "") -> Any:
        if key in body:
            return body.get(key)
        if existing is not None and key in existing.keys():
            return existing[key]
        return default

    name = str(get_value("name") or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="name is required.")

    start_date = _parse_tbgn_date(get_value("start_date"), "start_date")
    end_date = _parse_tbgn_date(get_value("end_date"), "end_date")
    if end_date < start_date:
        raise HTTPException(status_code=400, detail="end_date must be on or after start_date.")

    status = str(get_value("status", "draft") or "draft").strip().lower()
    if status not in TBGN_ALLOWED_STATUSES:
        raise HTTPException(status_code=400, detail="status must be draft or published.")

    geometry_text, geometry_obj = _normalize_tbgn_geometry(get_value("geometry", None))

    return {
        "name": name,
        "start_date": start_date.isoformat(),
        "end_date": end_date.isoformat(),
        "affected_lines": str(get_value("affected_lines") or "").strip(),
        "color": _normalize_tbgn_color(get_value("color", TBGN_DEFAULT_COLOR)),
        "geometry": geometry_text,
        "geometry_obj": geometry_obj,
        "status": status,
        "notes": str(get_value("notes") or "").strip(),
    }


def _parse_tbgn_geometry_text(value: Any) -> Optional[Any]:
    if value is None:
        return None
    raw = str(value or "").strip()
    if not raw:
        return None
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return None


def _tbgn_row_to_dict(row: sqlite3.Row, public: bool = False) -> Dict[str, Any]:
    data = {
        "id": row["id"],
        "name": row["name"],
        "start_date": row["start_date"],
        "end_date": row["end_date"],
        "affected_lines": row["affected_lines"] or "",
        "color": row["color"] or TBGN_DEFAULT_COLOR,
        "geometry": _parse_tbgn_geometry_text(row["geometry"]),
        "status": row["status"],
        "notes": row["notes"] or "",
    }

    if not public:
        data.update(
            {
                "created_by": row["created_by"] or "",
                "created_at": row["created_at"],
                "updated_at": row["updated_at"],
            }
        )

    return data

def _ensure_user_exists(email: str) -> bool:
    if _use_postgres_read_backend():
        try:
            with PostgresAppQueries() as pg:
                return bool(pg.get_user_by_email(email))
        except Exception as exc:
            raise _postgres_read_unavailable(exc)

    with get_db() as conn:
        row = conn.execute(
            "SELECT email FROM users WHERE lower(email) = ?",
            ((email or "").strip().lower(),),
        ).fetchone()
        return bool(row)


def _login_rate_limit_key(request: Request, email: str) -> str:
    client_host = request.client.host if request.client else "unknown"
    return f"{client_host}:{(email or '').strip().lower()}"


def _prune_login_failures(key: str, now_ts: float) -> List[float]:
    attempts = [
        ts for ts in LOGIN_FAILURES.get(key, [])
        if now_ts - ts < LOGIN_RATE_LIMIT_WINDOW_SECONDS
    ]
    if attempts:
        LOGIN_FAILURES[key] = attempts
    elif key in LOGIN_FAILURES:
        del LOGIN_FAILURES[key]
    return attempts


def _check_login_rate_limit(request: Request, email: str) -> None:
    key = _login_rate_limit_key(request, email)
    attempts = _prune_login_failures(key, time.time())
    if len(attempts) >= LOGIN_RATE_LIMIT_MAX_FAILURES:
        raise HTTPException(
            status_code=429,
            detail="Too many failed login attempts. Try again later.",
        )


def _record_login_failure(request: Request, email: str) -> None:
    key = _login_rate_limit_key(request, email)
    attempts = _prune_login_failures(key, time.time())
    attempts.append(time.time())
    LOGIN_FAILURES[key] = attempts


def _clear_login_failures(request: Request, email: str) -> None:
    key = _login_rate_limit_key(request, email)
    if key in LOGIN_FAILURES:
        del LOGIN_FAILURES[key]
    
def _normalize_application_target_type(value: Any) -> str:
    target_type = str(value or "rail_segment").strip().lower() or "rail_segment"
    if target_type not in VALID_APPLICATION_TARGET_TYPES:
        raise HTTPException(status_code=400, detail="Invalid target_type.")
    return target_type


def _default_asset_source(target_type: str) -> str:
    if target_type == "overhead_section":
        return "BOVENLEIDING_DATA"
    return "SPOOR_DATA"


def _default_asset_label(target_type: str, asset_id: str, segment_id: str = "") -> str:
    if target_type == "switch_junction":
        return f"Switch/Junction {asset_id or segment_id or '-'}"
    if target_type == "overhead_section":
        return f"Overhead section {asset_id or '-'}"
    return f"Rail segment {segment_id or asset_id or '-'}"


def _find_asset_conflict(
    conn: sqlite3.Connection,
    target_type: str,
    asset_id: str,
    project_start: str,
    project_end: str,
) -> Optional[Dict[str, Any]]:
    row = conn.execute(
        """
        SELECT
            a.application_id,
            a.status,
            a.submitted_at,
            a.submitted_by_email,
            t.target_index,
            coalesce(nullif(t.target_type, ''), 'rail_segment') AS target_type,
            coalesce(nullif(t.asset_id, ''), t.segment_id, '') AS asset_id,
            t.asset_label,
            t.asset_source,
            t.segment_id,
            t.line_id,
            t.line_name,
            coalesce(w.project_start, t.project_start) AS project_start,
            coalesce(w.project_end, t.project_end) AS project_end,
            w.window_index AS schedule_index,
            w.label AS schedule_label
        FROM applications a
        JOIN application_targets t
          ON t.application_id = a.application_id
        LEFT JOIN application_target_windows w
          ON w.target_id = t.id
        WHERE coalesce(nullif(t.target_type, ''), 'rail_segment') = ?
          AND coalesce(nullif(t.asset_id, ''), t.segment_id, '') = ?
          AND coalesce(w.project_start, t.project_start) < ?
          AND coalesce(w.project_end, t.project_end) > ?
        ORDER BY coalesce(w.project_start, t.project_start) ASC
        LIMIT 1
        """,
        (target_type, asset_id, project_end, project_start),
    ).fetchone()

    if not row:
        return None

    return {
        "application_id": row["application_id"],
        "status": row["status"],
        "submitted_at": row["submitted_at"],
        "submitted_by_email": row["submitted_by_email"],
        "target_index": row["target_index"],
        "target_type": row["target_type"],
        "asset_id": row["asset_id"],
        "asset_label": row["asset_label"],
        "asset_source": row["asset_source"],
        "segment_id": row["segment_id"],
        "line_id": row["line_id"],
        "line_name": row["line_name"],
        "project_start": row["project_start"],
        "project_end": row["project_end"],
        "schedule_index": row["schedule_index"],
        "schedule_label": row["schedule_label"],
    }


def _parse_json_field(raw: str, field_name: str) -> Any:
    try:
        return json.loads(raw)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Invalid JSON in {field_name}.") from e


@lru_cache(maxsize=4)
def _load_embedded_json_constant(path_str: str, constant_name: str) -> Any:
    path = Path(path_str)
    text = path.read_text(encoding="utf-8-sig", errors="replace").strip()

    if not text:
        raise RuntimeError(f"Prototype data file is empty: {path.name}")

    decoder = json.JSONDecoder()

    if text.startswith("{") or text.startswith("["):
        try:
            value, _ = decoder.raw_decode(text)
            return value
        except Exception as exc:
            raise RuntimeError(f"Invalid JSON in {path.name}") from exc

    const_pos = text.find(constant_name)
    if const_pos < 0:
        preview = text[:160]
        raise RuntimeError(
            f"Could not find {constant_name} in {path.name}. "
            f"First chars: {preview!r}"
        )

    eq_pos = text.find("=", const_pos)
    if eq_pos < 0:
        preview = text[:160]
        raise RuntimeError(
            f"Could not find assignment for {constant_name} in {path.name}. "
            f"First chars: {preview!r}"
        )

    payload = text[eq_pos + 1 :].strip()

    try:
        value, _ = decoder.raw_decode(payload)
        return value
    except Exception as exc:
        preview = payload[:200]
        raise RuntimeError(
            f"Unexpected prototype data format in {path.name}. "
            f"Payload starts with: {preview!r}"
        ) from exc


def _clean_haltes_line_select(value: Any) -> List[str]:
    if not value or value == "-":
        return []

    return [
        code.strip()
        for code in str(value).split("|")
        if code.strip() in HALTES_TRAM_CODES
    ]


def _format_haltes_line_text(codes: List[str]) -> str:
    if not codes:
        return "-"
    return " | ".join(str(int(code)) for code in codes)


@lru_cache(maxsize=1)
def _load_haltes_data(path_str: str) -> Dict[str, Any]:
    raw_data = _load_embedded_json_constant(path_str, "RAW_TRAMMETRO_PUNTEN_2026")
    features = raw_data.get("features") or []
    cleaned_features: List[Dict[str, Any]] = []

    for feature in features:
        properties = dict(feature.get("properties") or {})
        if properties.get("Modaliteit") != "Tram":
            continue

        tram_codes = _clean_haltes_line_select(properties.get("Lijn_select"))
        properties["Lijn_select"] = "|".join(tram_codes)
        properties["Lijn"] = _format_haltes_line_text(tram_codes)

        naam = properties.get("Naam", "")
        properties["Label"] = (
            f"{properties['Lijn']} - {naam}"
            if properties["Lijn"] != "-"
            else naam
        )

        if not properties["Lijn_select"]:
            continue

        cleaned_feature = dict(feature)
        cleaned_feature["properties"] = properties
        cleaned_features.append(cleaned_feature)

    return {
        "type": "FeatureCollection",
        "name": "HALTES_DATA",
        "features": cleaned_features,
    }


def _load_prototype_map_data() -> Dict[str, Any]:
    loaded: Dict[str, Any] = {}

    for api_key, (path, constant_name) in PROTOTYPE_DATA_FILES.items():
        if api_key == "haltes_data":
            loaded[api_key] = _load_haltes_data(str(path))
            continue
        loaded[api_key] = _load_embedded_json_constant(str(path), constant_name)

    return loaded


def _matches_file_signature(ext: str, chunk: bytes) -> bool:
    if ext == ".pdf":
        return chunk.startswith(b"%PDF-")
    if ext == ".png":
        return chunk.startswith(b"\x89PNG\r\n\x1a\n")
    if ext in {".jpg", ".jpeg"}:
        return chunk.startswith(b"\xff\xd8\xff")
    if ext == ".doc":
        return chunk.startswith(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1")
    if ext == ".docx":
        return chunk.startswith((b"PK\x03\x04", b"PK\x05\x06", b"PK\x07\x08"))
    return False


async def _save_validated_upload(upload: UploadFile, app_id: str) -> Dict[str, str]:
    original_name = _safe_name(upload.filename or "safety_plan")
    ext = Path(original_name).suffix.lower()

    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(status_code=400, detail=f"File type not allowed: {original_name}")

    content_type = (upload.content_type or "").split(";", 1)[0].strip().lower()
    allowed_types = ALLOWED_CONTENT_TYPES.get(ext, set())
    if content_type and content_type not in allowed_types and content_type not in GENERIC_CONTENT_TYPES:
        raise HTTPException(status_code=400, detail=f"Unexpected file content type: {original_name}")

    stored_name = f"{app_id}__{original_name}"
    out_path = UPLOADS_DIR / stored_name
    total_size = 0
    first_chunk = await upload.read(8192)

    if not first_chunk:
        raise HTTPException(status_code=400, detail=f"File is empty: {original_name}")

    if not _matches_file_signature(ext, first_chunk):
        raise HTTPException(status_code=400, detail=f"File signature not allowed: {original_name}")

    try:
        with out_path.open("wb") as fh:
            chunk = first_chunk
            while chunk:
                total_size += len(chunk)
                if total_size > MAX_FILE_SIZE_BYTES:
                    raise HTTPException(
                        status_code=400,
                        detail=(
                            f"File too large: {original_name}. "
                            f"Max size is {MAX_FILE_SIZE_BYTES // (1024 * 1024)} MB."
                        ),
                    )
                fh.write(chunk)
                chunk = await upload.read(1024 * 1024)
    except Exception:
        if out_path.exists():
            out_path.unlink()
        raise
    finally:
        await upload.close()

    return {
        "filename": original_name,
        "stored_filename": stored_name,
    }


def _delete_saved_uploads(items: List[Dict[str, str]]) -> None:
    for item in items:
        stored_name = item.get("stored_filename")
        if not stored_name:
            continue
        path = UPLOADS_DIR / Path(stored_name).name
        if path.exists():
            path.unlink()

def _admin_application_row_to_summary(row: sqlite3.Row) -> Dict[str, Any]:
    return {
        "item_type": "work_application",
        "application_id": row["application_id"],
        "submitted_at": row["submitted_at"],
        "status": row["status"],
        "submitted_by_email": row["submitted_by_email"],
        "person_mode": row["person_mode"],
        "work_source": row["work_source"],
        "urgency": row["urgency"],
        "vvw_measure": row["vvw_measure"],
    }

def _serialize_application_summary(conn: sqlite3.Connection, row: sqlite3.Row) -> Dict[str, Any]:
    targets = conn.execute(
        """
        SELECT id, target_index,
               coalesce(nullif(target_type, ''), 'rail_segment') AS target_type,
               coalesce(nullif(asset_id, ''), segment_id, '') AS asset_id,
               asset_label, asset_source,
               segment_id, line_id, line_name, work_mode,
               work_start_x, work_start_y, work_end_x, work_end_y,
               project_start, project_end
        FROM application_targets
        WHERE application_id = ?
        ORDER BY target_index ASC
        """,
        (row["application_id"],),
    ).fetchall()

    target_windows = conn.execute(
        """
        SELECT
            t.id AS target_id,
            w.window_index,
            w.project_start,
            w.project_end,
            w.label
        FROM application_targets t
        LEFT JOIN application_target_windows w
          ON w.target_id = t.id
        WHERE t.application_id = ?
        ORDER BY t.target_index ASC, w.window_index ASC
        """,
        (row["application_id"],),
    ).fetchall()

    people = conn.execute(
        """
        SELECT target_index, first_name, last_name, phone, email, employee_id
        FROM application_people
        WHERE application_id = ?
        ORDER BY CASE WHEN target_index IS NULL THEN -1 ELSE target_index END ASC
        """,
        (row["application_id"],),
    ).fetchall()

    uploads = conn.execute(
        """
        SELECT original_filename, stored_filename
        FROM application_uploads
        WHERE application_id = ?
        ORDER BY id ASC
        """,
        (row["application_id"],),
    ).fetchall()

    windows_by_target: Dict[int, List[Dict[str, Any]]] = {}
    for t in targets:
        windows_by_target[t["id"]] = []

    for w in target_windows:
        target_id = w["target_id"]
        if target_id not in windows_by_target:
            windows_by_target[target_id] = []
        if w["window_index"] is None:
            continue
        windows_by_target[target_id].append(
            {
                "project_start": w["project_start"],
                "project_end": w["project_end"],
                "label": w["label"] or "Custom work",
            }
        )

    serialized_targets: List[Dict[str, Any]] = []
    for t in targets:
        target_type = _normalize_application_target_type(t["target_type"])
        asset_id = str(t["asset_id"] or t["segment_id"] or "").strip()
        segment_id = str(t["segment_id"] or "").strip()
        asset_label = str(t["asset_label"] or "").strip() or _default_asset_label(
            target_type,
            asset_id,
            segment_id,
        )
        asset_source = str(t["asset_source"] or "").strip() or _default_asset_source(target_type)
        schedules = windows_by_target.get(t["id"], [])
        if not schedules:
            schedules = [
                {
                    "project_start": t["project_start"],
                    "project_end": t["project_end"],
                    "label": "Custom work",
                }
            ]

        serialized_targets.append(
            {
                "target_index": t["target_index"],
                "target_type": target_type,
                "asset_id": asset_id,
                "asset_label": asset_label,
                "asset_source": asset_source,
                "segment_id": t["segment_id"],
                "line_id": t["line_id"],
                "line_name": t["line_name"],
                "work_mode": t["work_mode"],
                "work_start_point": (
                    {"x": t["work_start_x"], "y": t["work_start_y"]}
                    if t["work_start_x"] is not None and t["work_start_y"] is not None
                    else None
                ),
                "work_end_point": (
                    {"x": t["work_end_x"], "y": t["work_end_y"]}
                    if t["work_end_x"] is not None and t["work_end_y"] is not None
                    else None
                ),
                "project_start": t["project_start"],
                "project_end": t["project_end"],
                "schedules": schedules,
            }
        )

    return {
        "item_type": "work_application",
        "application_id": row["application_id"],
        "submitted_at": row["submitted_at"],
        "status": row["status"],
        "submitted_by_email": row["submitted_by_email"],
        "person_mode": row["person_mode"],
        "admin_note": row["admin_note"],
        "decision_message": row["decision_message"],
        "work_details": {
            "description": row["work_description"],
            "source": row["work_source"],
            "urgency": row["urgency"],
            "affected_lines": row["affected_lines"],
            "notes": row["work_notes"],
        },
        "contact_details": {
            "coordinator": row["coordinator"],
            "vvw_measure": row["vvw_measure"],
        },
        "targets": serialized_targets,
        "people": [
            {
                "target_index": p["target_index"],
                "first_name": p["first_name"],
                "last_name": p["last_name"],
                "phone": p["phone"],
                "email": p["email"],
                "employee_id": p["employee_id"],
            }
            for p in people
        ],
        "uploads": [
            {
                "filename": u["original_filename"],
                "stored_filename": u["stored_filename"],
            }
            for u in uploads
        ],
    }


def _apps_for_email(email: str) -> List[Dict[str, Any]]:
    email_l = (email or "").strip().lower()
    with get_db() as conn:
        rows = conn.execute(
            """
            SELECT *
            FROM applications
            WHERE lower(submitted_by_email) = ?
            ORDER BY submitted_at DESC
            """,
            (email_l,),
        ).fetchall()
        return [_serialize_application_summary(conn, row) for row in rows]


def _parse_iso_datetime_safe(value: str | None) -> Optional[datetime]:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).strip())
    except Exception:
        return None


def _parse_iso_date_safe(value: str | None) -> Optional[date]:
    if not value:
        return None
    raw = str(value).strip()
    if not raw:
        return None
    try:
        return date.fromisoformat(raw[:10])
    except Exception:
        return None


def _ranges_overlap(
    permit_start: Optional[datetime],
    permit_end: Optional[datetime],
    wior_start: Optional[date],
    wior_end: Optional[date],
) -> bool:
    if not permit_start or not permit_end or not wior_start or not wior_end:
        return False

    permit_start_d = permit_start.date()
    permit_end_d = permit_end.date()

    return wior_start <= permit_end_d and wior_end >= permit_start_d


def _coerce_date_value(value: Any) -> Optional[date]:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if value is None:
        return None

    raw = str(value).strip()
    if not raw:
        return None

    dt_value = _parse_iso_datetime_safe(raw)
    if dt_value:
        return dt_value.date()

    return _parse_iso_date_safe(raw)


def _date_overlaps_day(start: Any, end: Any, selected_date: date) -> bool:
    start_d = _coerce_date_value(start)
    end_d = _coerce_date_value(end)
    if not start_d or not end_d:
        return False
    return start_d <= selected_date <= end_d


@app.get("/health")
def health_check():
    try:
        conn = sqlite3.connect(str(DB_PATH))
        conn.execute("SELECT 1")
        conn.close()
        db_status = "ok"
    except Exception as e:
        db_status = f"error: {str(e)}"

    uploads_ok = UPLOADS_DIR.is_dir()
    postgres_status = check_postgres_health()
    postgres_ok = postgres_status.get("status") in {"ok", "not_configured"}
    resolved_backend = _app_db_backend()
    raw_backend = os.getenv("APP_DB_BACKEND", "sqlite").strip() or "sqlite"

    return {
        "status": "ok" if db_status == "ok" and uploads_ok and postgres_ok else "degraded",
        "timestamp": datetime.utcnow().isoformat(),
        "database": db_status,
        "sqlite": {
            "status": db_status,
            "path": str(DB_PATH),
        },
        "app_db_backend": {
            "raw": raw_backend,
            "resolved": resolved_backend,
            "selected_read_routes_backend": resolved_backend,
            "selected_write_backend": resolved_backend,
            "selected_read_routes": FEATURE_FLAGGED_READ_ROUTE_PATHS,
            "postgres_configured": bool(postgres_status.get("configured")),
            "postgres_available": postgres_status.get("status") == "ok",
            "sqlite_status": db_status,
        },
        "postgres": postgres_status,
        "uploads_folder": "ok" if uploads_ok else "missing",
    }


@app.get("/openapi.json")
def admin_openapi(request: Request):
    _require_admin(request)
    return JSONResponse(
        get_openapi(
            title=app.title,
            version="1.0.0",
            routes=app.routes,
        )
    )


@app.get("/docs")
def admin_docs(request: Request):
    _require_admin(request)
    return get_swagger_ui_html(
        openapi_url="/openapi.json",
        title=f"{app.title} - Swagger UI",
    )


# -------------------- pages --------------------
@app.get("/")
def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


# -------------------- auth --------------------
@app.get("/api/me")
def me(request: Request) -> Dict[str, Any]:
    user = _get_user(request)
    return {"authenticated": bool(user), "user": user}


@app.post("/api/login")
async def login(request: Request) -> JSONResponse:
    body = await request.json()
    email = str(body.get("email", "")).strip().lower()
    password = str(body.get("password", "")).strip()

    if not email or "@" not in email:
        if _audit_runtime_enabled():
            write_audit_log(
                actor_email=email or None,
                actor_type="unknown",
                action_scope="user_action",
                action="login_failed",
                entity_type="user",
                entity_id=email or None,
                metadata={"failure_category": "invalid_email", "attempted_email": email or None},
                request=request,
            )
        raise HTTPException(status_code=400, detail="Email looks invalid.")
    if not password:
        if _audit_runtime_enabled():
            write_audit_log(
                actor_email=email,
                actor_type="unknown",
                action_scope="user_action",
                action="login_failed",
                entity_type="user",
                entity_id=email,
                metadata={"failure_category": "missing_password", "attempted_email": email},
                request=request,
            )
        raise HTTPException(status_code=400, detail="Password is required.")

    _check_login_rate_limit(request, email)

    if _use_postgres_read_backend():
        try:
            with PostgresAppQueries() as pg:
                row = pg.get_user_by_email(email)
        except Exception as exc:
            raise _postgres_read_unavailable(exc)
    else:
        with get_db() as conn:
            row = conn.execute(
                "SELECT email, password_hash, is_admin FROM users WHERE lower(email) = ?",
                (email,),
            ).fetchone()

    if not row:
        _record_login_failure(request, email)
        if _audit_runtime_enabled():
            write_audit_log(
                actor_email=email,
                actor_type="unknown",
                action_scope="user_action",
                action="login_failed",
                entity_type="user",
                entity_id=email,
                metadata={"failure_category": "invalid_credentials", "attempted_email": email},
                request=request,
            )
        raise HTTPException(status_code=401, detail="Invalid email or password.")
    if not verify_password(password, row["password_hash"]):
        _record_login_failure(request, email)
        if _audit_runtime_enabled():
            write_audit_log(
                actor_email=email,
                actor_type="admin" if bool(row["is_admin"]) else "user",
                action_scope="user_action",
                action="login_failed",
                entity_type="user",
                entity_id=email,
                metadata={"failure_category": "invalid_credentials", "attempted_email": email},
                request=request,
            )
        raise HTTPException(status_code=401, detail="Invalid email or password.")

    user = {
        "email": row["email"],
        "is_admin": bool(row["is_admin"]),
    }
    _clear_login_failures(request, email)
    request.session["user"] = user
    if _audit_runtime_enabled():
        write_audit_log(
            actor_email=email,
            actor_type="admin" if bool(row["is_admin"]) else "user",
            action_scope="user_action",
            action="login_success",
            entity_type="user",
            entity_id=email,
            metadata={"is_admin": bool(row["is_admin"])},
            request=request,
        )
    return JSONResponse({"ok": True, "user": user})


@app.post("/api/logout")
def logout(request: Request) -> JSONResponse:
    request.session.clear()
    return JSONResponse({"ok": True})


@app.get("/api/settings/activity")
def settings_activity(
    request: Request,
    limit: int = 50,
    offset: int = 0,
    action_scope: Optional[str] = None,
) -> JSONResponse:
    user = _require_user(request)
    email = str(user.get("email") or "").strip().lower()
    try:
        items = list_user_activity(
            actor_email=email,
            limit=limit,
            offset=offset,
            action_scope=action_scope,
        )
    except Exception as exc:
        raise _postgres_read_unavailable(exc)
    return JSONResponse({"ok": True, "items": items})


@app.get("/api/admin/audit-logs")
def admin_audit_logs(
    request: Request,
    actor_email: Optional[str] = None,
    action_scope: Optional[str] = None,
    entity_type: Optional[str] = None,
    entity_id: Optional[str] = None,
    limit: int = 100,
    offset: int = 0,
) -> JSONResponse:
    _require_admin(request)
    try:
        items = list_admin_audit_logs(
            actor_email=actor_email,
            action_scope=action_scope,
            entity_type=entity_type,
            entity_id=entity_id,
            limit=limit,
            offset=offset,
        )
    except Exception as exc:
        raise _postgres_read_unavailable(exc)
    return JSONResponse({"ok": True, "items": items})

class WiorConflictTarget(BaseModel):
    segment_id: str
    target_type: Optional[str] = None
    project_start: str
    project_end: str
    target_index: Optional[int] = None
    schedule_index: Optional[int] = None
    schedule_label: Optional[str] = None


class WiorConflictCheckRequest(BaseModel):
    targets: List[WiorConflictTarget]


def _legacy_wior_conflicts(targets: List[WiorConflictTarget]) -> List[Dict[str, Any]]:
    wior_rows = get_cached_wior_serving_features(limit=5000, mode="all")

    conflicts: List[Dict[str, Any]] = []

    for target_index, target in enumerate(targets):
        if target.target_type and _normalize_application_target_type(target.target_type) == "overhead_section":
            continue
        segment_id = str(target.segment_id or "").strip()
        project_start = _parse_iso_datetime_safe(target.project_start)
        project_end = _parse_iso_datetime_safe(target.project_end)
        resolved_target_index = target.target_index if target.target_index is not None else target_index
        resolved_schedule_index = target.schedule_index if target.schedule_index is not None else 0
        resolved_schedule_label = str(target.schedule_label or "").strip() or "Custom work"

        if not segment_id or not project_start or not project_end:
            continue

        for wior in wior_rows:
            segment_ids = wior.get("segment_ids") or []
            if segment_id not in segment_ids:
                continue

            wior_start = _parse_iso_date_safe(wior.get("start_date"))
            wior_end = _parse_iso_date_safe(wior.get("end_date"))

            if not _ranges_overlap(project_start, project_end, wior_start, wior_end):
                continue

            conflicts.append(
                {
                    "target_index": resolved_target_index,
                    "schedule_index": resolved_schedule_index,
                    "schedule_label": resolved_schedule_label,
                    "matched_segment_id": segment_id,
                    "project_start": target.project_start,
                    "project_end": target.project_end,
                    "wior_id": wior.get("wior_id"),
                    "project_code": wior.get("project_code"),
                    "project_name": wior.get("project_name"),
                    "status": wior.get("status"),
                    "work_type": wior.get("work_type"),
                    "start_date": wior.get("start_date"),
                    "end_date": wior.get("end_date"),
                }
            )
    return conflicts


def _wior_conflict_response(
    conflicts: List[Dict[str, Any]],
    backend: str = "legacy",
    include_backend: bool = False,
    extra: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    payload = {
        "ok": True,
        "has_conflicts": len(conflicts) > 0,
        "conflict_count": len(conflicts),
        "conflicts": conflicts,
    }
    if include_backend:
        payload["backend"] = backend
    if extra:
        payload.update(extra)
    return payload


def _postgis_wior_mirror_debug(status: Dict[str, Any]) -> Dict[str, Any]:
    safe_keys = (
        "database_url_set",
        "reachable",
        "wior_table_exists",
        "tram_segments_table_exists",
        "row_count",
        "latest_updated_at",
        "latest_last_built_at",
        "available",
        "reason",
        "error_type",
    )
    return {key: status.get(key) for key in safe_keys if key in status}


def _audit_wior_conflict_check(
    request: Request,
    actor_email: str,
    backend_used: str,
    target_count: int,
    conflict_count: int,
    fallback_used: bool = False,
    fallback_reason: Optional[str] = None,
) -> None:
    if not _audit_runtime_enabled():
        return
    metadata = {
        "backend": backend_used,
        "fallback_used": bool(fallback_used),
        "conflict_count": int(conflict_count or 0),
        "target_count": int(target_count or 0),
    }
    if fallback_reason:
        metadata["fallback_reason"] = fallback_reason
    write_audit_log(
        actor_email=actor_email,
        actor_type="user",
        action_scope="system_action",
        action="wior_conflict_checked",
        entity_type="wior_conflict_check",
        metadata=metadata,
        request=request,
    )
    if fallback_used:
        write_audit_log(
            actor_email=actor_email,
            actor_type="user",
            action_scope="system_action",
            action="wior_postgis_fallback_to_legacy",
            entity_type="wior_conflict_check",
            metadata=metadata,
            request=request,
        )


#----------------------ADMIN_FEATURES----------------
@app.get("/admin")
def admin_page(request: Request) -> FileResponse:
    _require_admin(request)
    return FileResponse(STATIC_DIR / "admin.html")




# -------------------- map data --------------------
@app.get("/api/manifest")
def manifest(request: Request) -> Dict[str, Any]:
    _require_user(request)
    m = tile_server.manifest()
    m["map_id"] = "gvb_amsterdam"
    return m


@app.get("/api/features")
def features(request: Request) -> Dict[str, Any]:
    _require_user(request)
    return feature_index.raw


@app.get("/api/map-data")
def map_data(request: Request) -> JSONResponse:
    _require_user(request)
    return JSONResponse(_load_prototype_map_data())


@app.get("/tiles/{z}/{x}/{y}.png")
def tile(z: int, x: int, y: int, request: Request) -> Response:
    _require_user(request)
    mtime = tile_server._mtime()
    png_bytes = tile_server.render_tile_png_bytes(mtime=mtime, z=z, x=x, y=y)

    if png_bytes is None:
        raise HTTPException(status_code=404, detail="Tile out of range")

    headers = {"Cache-Control": "public, max-age=86400"}
    return Response(content=png_bytes, media_type="image/png", headers=headers)



def _utc_timestamp() -> str:
    return datetime.now(timezone.utc).isoformat()


def _payload_float(payload: Dict[str, Any], key: str) -> Optional[float]:
    if key not in payload:
        return None
    try:
        value = float(payload[key])
    except (TypeError, ValueError):
        return None
    if not math.isfinite(value):
        return None
    return value


def _valid_lng_lat(lng: Optional[float], lat: Optional[float]) -> bool:
    return (
        lng is not None
        and lat is not None
        and -180 <= lng <= 180
        and -90 <= lat <= 90
    )


def _valid_pixel_xy(x: Optional[float], y: Optional[float]) -> bool:
    return x is not None and y is not None


def _click_radius_m(payload: Dict[str, Any]) -> float:
    if "radius_m" not in payload:
        return 30.0
    try:
        radius_m = float(payload["radius_m"])
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="radius_m must be numeric")
    if not math.isfinite(radius_m) or radius_m <= 0:
        raise HTTPException(status_code=400, detail="radius_m must be positive")
    return min(radius_m, 250.0)


def _pixel_click_result(x: float, y: float) -> Dict[str, Any]:
    result = feature_index.hit_test(x=x, y=y)
    result["map_px"] = {"x": x, "y": y}
    result["timestamp"] = _utc_timestamp()
    return result


def _postgis_no_hit_result(radius_m: float, reason: str) -> Dict[str, Any]:
    return {
        "hit": False,
        "hit_type": None,
        "feature": None,
        "debug": {
            "mode": "postgis_lnglat",
            "radius_m": radius_m,
            "reason": reason,
        },
        "map_px": None,
        "timestamp": _utc_timestamp(),
    }


def _postgis_click_result(segment: Dict[str, Any], radius_m: float) -> Dict[str, Any]:
    distance_m = segment.get("distance_m")
    segment_id = segment.get("segment_id")
    return {
        "hit": True,
        "hit_type": "segment",
        "feature": {
            "id": segment_id,
            "segment_id": segment_id,
            "line_id": segment.get("line_id"),
            "line_name": segment.get("line_name"),
            "source": segment.get("source"),
            "bookable": segment.get("bookable"),
            "distance_m": distance_m,
            "geometry": segment.get("geometry"),
        },
        "debug": {
            "mode": "postgis_lnglat",
            "radius_m": radius_m,
            "distance_m": distance_m,
        },
        "map_px": None,
        "timestamp": _utc_timestamp(),
    }


def _postgis_unavailable_reason() -> str:
    if is_postgis_click_available():
        return "no_segment_within_radius"
    return "postgis_unavailable"


@app.post("/api/click")
async def click(payload: Dict[str, Any], request: Request) -> JSONResponse:
    _require_user(request)
    lng = _payload_float(payload, "lng")
    lat = _payload_float(payload, "lat")
    x = _payload_float(payload, "x")
    y = _payload_float(payload, "y")
    has_lng_lat = _valid_lng_lat(lng, lat)
    has_pixel_xy = _valid_pixel_xy(x, y)

    if has_lng_lat:
        radius_m = _click_radius_m(payload)
        try:
            segment = find_nearest_segment_postgis(lng, lat, radius_m=radius_m)
        except Exception:
            segment = None

        if segment is not None:
            return JSONResponse(_postgis_click_result(segment, radius_m))
        if has_pixel_xy:
            return JSONResponse(_pixel_click_result(x, y))

        reason = _postgis_unavailable_reason()
        return JSONResponse(_postgis_no_hit_result(radius_m, reason))

    if "lng" in payload or "lat" in payload:
        if not has_pixel_xy:
            raise HTTPException(status_code=400, detail="Payload must include valid lng,lat or numeric x,y")

    if has_pixel_xy:
        return JSONResponse(_pixel_click_result(x, y))

    raise HTTPException(status_code=400, detail="Payload must include valid lng,lat or numeric x,y")

# -------------------- WIOR data pipeline --------------------
@app.post("/api/wior/refresh")
def api_wior_refresh(request: Request) -> JSONResponse:
    _require_admin(request)
    try:
        result = sync_wior_data()
        return JSONResponse(result)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"WIOR refresh failed: {exc}")


@app.get("/api/wior/features")
def api_wior_features(request: Request, limit: int = 1000, mode: str = "active") -> JSONResponse:
    _require_user(request)
    try:
        features = get_cached_wior_serving_features(limit=limit, mode=mode)

        geojson_features = []
        for item in features:
            geojson_features.append(
                {
                    "type": "Feature",
                    "properties": {
                        "wior_id": item["wior_id"],
                        "project_code": item["project_code"],
                        "project_name": item["project_name"],
                        "description": item["description"],
                        "status": item["status"],
                        "work_type": item["work_type"],
                        "start_date": item["start_date"],
                        "end_date": item["end_date"],
                        "is_active": item["is_active"],
                        "is_upcoming_7d": item["is_upcoming_7d"],
                        "is_upcoming_30d": item["is_upcoming_30d"],
                        "is_expired": item["is_expired"],
                        "last_built_at": item["last_built_at"],
                    },
                    "geometry": item["geometry"],
                }
            )

        return JSONResponse(
            {
                "type": "FeatureCollection",
                "features": geojson_features,
                "count": len(geojson_features),
                "mode": mode,
            }
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to load WIOR features: {exc}")
    

@app.post("/api/wior/conflicts/check")
def api_wior_conflicts_check(
    payload: WiorConflictCheckRequest,
    request: Request,
    backend: str = "auto",
) -> JSONResponse:
    user = _require_user(request)
    actor_email = str(user.get("email") or "").strip().lower()

    targets = payload.targets or []
    if not targets:
        raise HTTPException(status_code=400, detail="At least one target is required.")

    resolved_backend = str(backend or "auto").strip().lower()
    if resolved_backend not in {"auto", "legacy", "postgis", "compare"}:
        raise HTTPException(status_code=400, detail="backend must be auto, legacy, postgis, or compare.")

    if resolved_backend == "legacy":
        legacy_conflicts = _legacy_wior_conflicts(targets)
        response_payload = _wior_conflict_response(legacy_conflicts, backend="legacy")
        _audit_wior_conflict_check(
            request,
            actor_email,
            backend_used="legacy",
            target_count=len(targets),
            conflict_count=len(legacy_conflicts),
        )
        return JSONResponse(response_payload)

    postgis_status = get_postgis_wior_mirror_status()
    postgis_debug = _postgis_wior_mirror_debug(postgis_status)
    postgis_available = bool(postgis_status.get("available"))
    postgis_unavailable_reason = str(postgis_status.get("reason") or "postgis_unavailable")

    if resolved_backend == "postgis":
        if not postgis_available:
            raise HTTPException(
                status_code=503,
                detail=f"PostGIS WIOR conflict backend unavailable: {postgis_unavailable_reason}",
            )
        try:
            postgis_conflicts = find_wior_conflicts_postgis(targets, buffer_m=10.0)
        except Exception as exc:
            raise HTTPException(status_code=503, detail=f"PostGIS WIOR conflict backend unavailable: {exc}")
        response_payload = _wior_conflict_response(
            postgis_conflicts,
            backend="postgis",
            include_backend=True,
            extra={
                "fallback_used": False,
                "postgis_mirror": postgis_debug,
            },
        )
        _audit_wior_conflict_check(
            request,
            actor_email,
            backend_used="postgis",
            target_count=len(targets),
            conflict_count=len(postgis_conflicts),
        )
        return JSONResponse(response_payload)

    if resolved_backend == "auto":
        if postgis_available:
            try:
                postgis_conflicts = find_wior_conflicts_postgis(targets, buffer_m=10.0)
                response_payload = _wior_conflict_response(
                    postgis_conflicts,
                    backend="postgis",
                    include_backend=True,
                    extra={
                        "fallback_used": False,
                        "postgis_mirror": postgis_debug,
                    },
                )
                _audit_wior_conflict_check(
                    request,
                    actor_email,
                    backend_used="postgis",
                    target_count=len(targets),
                    conflict_count=len(postgis_conflicts),
                )
                return JSONResponse(response_payload)
            except Exception as exc:
                postgis_unavailable_reason = "postgis_error"
                postgis_debug = {
                    **postgis_debug,
                    "available": False,
                    "reason": postgis_unavailable_reason,
                    "error_type": type(exc).__name__,
                }

        legacy_conflicts = _legacy_wior_conflicts(targets)
        response_payload = _wior_conflict_response(
            legacy_conflicts,
            backend="legacy",
            include_backend=True,
            extra={
                "fallback_used": True,
                "fallback_reason": postgis_unavailable_reason,
                "postgis_mirror": postgis_debug,
            },
        )
        _audit_wior_conflict_check(
            request,
            actor_email,
            backend_used="legacy",
            target_count=len(targets),
            conflict_count=len(legacy_conflicts),
            fallback_used=True,
            fallback_reason=postgis_unavailable_reason,
        )
        return JSONResponse(response_payload)

    legacy_conflicts = _legacy_wior_conflicts(targets)
    if not postgis_available:
        response_payload = {
            "ok": True,
            "backend": "compare",
            "postgis_available": False,
            "postgis_mirror": postgis_debug,
            "legacy": _wior_conflict_response(legacy_conflicts, backend="legacy", include_backend=True),
            "postgis": {
                "ok": False,
                "backend": "postgis",
                "error": postgis_unavailable_reason,
            },
        }
        _audit_wior_conflict_check(
            request,
            actor_email,
            backend_used="compare",
            target_count=len(targets),
            conflict_count=len(legacy_conflicts),
        )
        return JSONResponse(response_payload)

    try:
        postgis_conflicts = find_wior_conflicts_postgis(targets, buffer_m=10.0)
    except Exception as exc:
        response_payload = {
            "ok": True,
            "backend": "compare",
            "postgis_available": True,
            "postgis_mirror": postgis_debug,
            "legacy": _wior_conflict_response(legacy_conflicts, backend="legacy", include_backend=True),
            "postgis": {
                "ok": False,
                "backend": "postgis",
                "error": str(exc),
                "error_type": type(exc).__name__,
            },
        }
        _audit_wior_conflict_check(
            request,
            actor_email,
            backend_used="compare",
            target_count=len(targets),
            conflict_count=len(legacy_conflicts),
        )
        return JSONResponse(response_payload)

    legacy_refs = {
        (item.get("wior_id"), item.get("matched_segment_id"))
        for item in legacy_conflicts
    }
    postgis_refs = {
        (item.get("wior_id"), item.get("matched_segment_id"))
        for item in postgis_conflicts
    }
    response_payload = {
        "ok": True,
        "backend": "compare",
        "postgis_available": True,
        "postgis_mirror": postgis_debug,
        "legacy": _wior_conflict_response(legacy_conflicts, backend="legacy", include_backend=True),
        "postgis": _wior_conflict_response(postgis_conflicts, backend="postgis", include_backend=True),
        "differences": {
            "legacy_only": sorted(list(legacy_refs - postgis_refs)),
            "postgis_only": sorted(list(postgis_refs - legacy_refs)),
        },
    }
    _audit_wior_conflict_check(
        request,
        actor_email,
        backend_used="compare",
        target_count=len(targets),
        conflict_count=len(legacy_conflicts) + len(postgis_conflicts),
    )
    return JSONResponse(response_payload)


@app.get("/api/wior/status")
def api_wior_status(request: Request) -> JSONResponse:
    _require_user(request)
    try:
        features = get_cached_wior_serving_features(limit=1, mode="all")
        return JSONResponse(
            {
                "ok": True,
                "has_data": len(features) > 0,
                "sample_count": len(features),
            }
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to read WIOR status: {exc}")


@app.get("/api/timeline/overview")
def api_timeline_overview(
    request: Request,
    start: Optional[str] = None,
    days: int = 84,
) -> JSONResponse:
    _require_user(request)

    start_d = _parse_iso_date_safe(start) if start else date.today()
    if not start_d:
        raise HTTPException(status_code=400, detail="start must be YYYY-MM-DD")

    days = max(1, min(int(days or 84), 180))
    range_end_d = start_d + timedelta(days=days)
    range_start_dt = datetime.combine(start_d, datetime.min.time()).isoformat()
    range_end_dt = datetime.combine(range_end_d, datetime.min.time()).isoformat()

    items_by_date: Dict[str, Dict[str, Any]] = {}
    for offset in range(days):
        current = start_d + timedelta(days=offset)
        weekday = DUTCH_WEEKDAY_SHORT[current.weekday()]
        items_by_date[current.isoformat()] = {
            "date": current.isoformat(),
            "week": current.isocalendar().week,
            "weekday": weekday,
            "label": f"{weekday.capitalize()} {current.day}",
            "internal_count": 0,
            "wior_count": 0,
            "tbgn_count": 0,
            "total_count": 0,
            "has_bb": False,
            "has_warning": False,
        }

    with get_db() as conn:
        rows = conn.execute(
            """
            SELECT
                a.urgency,
                a.vvw_measure,
                coalesce(w.project_start, t.project_start) AS project_start,
                coalesce(w.project_end, t.project_end) AS project_end
            FROM applications a
            JOIN application_targets t
              ON t.application_id = a.application_id
            LEFT JOIN application_target_windows w
              ON w.target_id = t.id
            WHERE a.status IN ('submitted', 'approved')
              AND coalesce(w.project_start, t.project_start) < ?
              AND coalesce(w.project_end, t.project_end) >= ?
            """,
            (range_end_dt, range_start_dt),
        ).fetchall()

    for row in rows:
        start_dt = _parse_iso_datetime_safe(row["project_start"])
        end_dt = _parse_iso_datetime_safe(row["project_end"])
        if not start_dt or not end_dt:
            continue

        overlap_start = max(start_dt.date(), start_d)
        overlap_end = min(end_dt.date(), range_end_d - timedelta(days=1))
        if overlap_end < overlap_start:
            continue

        has_bb = str(row["vvw_measure"] or "").strip().upper() == "BB"
        urgency = str(row["urgency"] or "").strip().lower()
        has_warning = urgency in {"high", "urgent"}

        current = overlap_start
        while current <= overlap_end:
            key = current.isoformat()
            item = items_by_date.get(key)
            if item:
                item["internal_count"] += 1
                item["total_count"] += 1
                item["has_bb"] = item["has_bb"] or has_bb
                item["has_warning"] = item["has_warning"] or has_warning
            current += timedelta(days=1)

    wior_rows = get_cached_wior_serving_features(limit=5000, mode="all")
    range_last_day = range_end_d - timedelta(days=1)
    for wior in wior_rows:
        wior_start = _parse_iso_date_safe(wior.get("start_date"))
        wior_end = _parse_iso_date_safe(wior.get("end_date"))
        if not wior_start or not wior_end:
            continue

        overlap_start = max(wior_start, start_d)
        overlap_end = min(wior_end, range_last_day)
        if overlap_end < overlap_start:
            continue

        current = overlap_start
        while current <= overlap_end:
            key = current.isoformat()
            item = items_by_date.get(key)
            if item:
                item["wior_count"] += 1
                item["total_count"] += 1
            current += timedelta(days=1)

    with get_db() as conn:
        tbgn_rows = conn.execute(
            """
            SELECT start_date, end_date
            FROM tbgn_projects
            WHERE status = 'published'
              AND start_date < ?
              AND end_date >= ?
            """,
            (range_end_d.isoformat(), start_d.isoformat()),
        ).fetchall()

    for row in tbgn_rows:
        tbgn_start = _parse_iso_date_safe(row["start_date"])
        tbgn_end = _parse_iso_date_safe(row["end_date"])
        if not tbgn_start or not tbgn_end:
            continue

        overlap_start = max(tbgn_start, start_d)
        overlap_end = min(tbgn_end, range_last_day)
        if overlap_end < overlap_start:
            continue

        current = overlap_start
        while current <= overlap_end:
            key = current.isoformat()
            item = items_by_date.get(key)
            if item:
                item["tbgn_count"] += 1
                item["total_count"] += 1
            current += timedelta(days=1)

    return JSONResponse(
        {
            "ok": True,
            "start": start_d.isoformat(),
            "days": days,
            "items": list(items_by_date.values()),
        }
    )


@app.get("/api/timeline/day")
def api_timeline_day(request: Request, date: str) -> JSONResponse:
    _require_user(request)

    selected_date = _parse_iso_date_safe(date)
    if not selected_date:
        raise HTTPException(status_code=400, detail="date must be YYYY-MM-DD")

    day_start_dt = datetime.combine(selected_date, datetime.min.time()).isoformat()
    day_end_dt = datetime.combine(selected_date + timedelta(days=1), datetime.min.time()).isoformat()

    with get_db() as conn:
        rows = conn.execute(
            """
            SELECT
                a.application_id,
                a.status,
                a.work_description,
                a.work_source,
                a.urgency,
                a.vvw_measure,
                coalesce(nullif(t.target_type, ''), 'rail_segment') AS target_type,
                coalesce(nullif(t.asset_id, ''), t.segment_id, '') AS asset_id,
                t.asset_label,
                t.asset_source,
                t.segment_id,
                t.line_id,
                t.line_name,
                coalesce(w.project_start, t.project_start) AS project_start,
                coalesce(w.project_end, t.project_end) AS project_end,
                coalesce(w.label, 'Custom work') AS schedule_label
            FROM applications a
            JOIN application_targets t
              ON t.application_id = a.application_id
            LEFT JOIN application_target_windows w
              ON w.target_id = t.id
            WHERE a.status IN ('submitted', 'approved')
              AND coalesce(w.project_start, t.project_start) < ?
              AND coalesce(w.project_end, t.project_end) >= ?
            ORDER BY coalesce(w.project_start, t.project_start) ASC
            """,
            (day_end_dt, day_start_dt),
        ).fetchall()

    items: List[Dict[str, Any]] = []
    for row in rows:
        target_type = _normalize_application_target_type(row["target_type"])
        asset_id = str(row["asset_id"] or row["segment_id"] or "").strip()
        segment_id = str(row["segment_id"] or "").strip()
        items.append(
            {
                "type": "internal",
                "application_id": row["application_id"],
                "status": row["status"],
                "target_type": target_type,
                "asset_id": asset_id,
                "asset_label": str(row["asset_label"] or "").strip() or _default_asset_label(
                    target_type,
                    asset_id,
                    segment_id,
                ),
                "asset_source": str(row["asset_source"] or "").strip() or _default_asset_source(target_type),
                "segment_id": row["segment_id"],
                "line_id": row["line_id"],
                "line_name": row["line_name"],
                "project_start": row["project_start"],
                "project_end": row["project_end"],
                "schedule_label": row["schedule_label"] or "Custom work",
                "work_description": row["work_description"],
                "work_source": row["work_source"],
                "urgency": row["urgency"],
                "vvw_measure": row["vvw_measure"],
            }
        )

    wior_rows = get_cached_wior_serving_features(limit=5000, mode="all")
    for wior in wior_rows:
        if not _date_overlaps_day(wior.get("start_date"), wior.get("end_date"), selected_date):
            continue

        items.append(
            {
                "type": "wior",
                "wior_id": wior.get("wior_id"),
                "project_code": wior.get("project_code"),
                "project_name": wior.get("project_name"),
                "status": wior.get("status"),
                "work_type": wior.get("work_type"),
                "start_date": wior.get("start_date"),
                "end_date": wior.get("end_date"),
                "segment_ids": wior.get("segment_ids") or [],
            }
        )

    with get_db() as conn:
        tbgn_rows = conn.execute(
            """
            SELECT *
            FROM tbgn_projects
            WHERE status = 'published'
              AND start_date <= ?
              AND end_date >= ?
            ORDER BY start_date ASC, name ASC
            """,
            (selected_date.isoformat(), selected_date.isoformat()),
        ).fetchall()

    for row in tbgn_rows:
        project = _tbgn_row_to_dict(row, public=True)
        items.append(
            {
                "type": "tbgn",
                "id": project["id"],
                "name": project["name"],
                "start_date": project["start_date"],
                "end_date": project["end_date"],
                "affected_lines": project["affected_lines"],
                "color": project["color"],
                "geometry": project["geometry"],
                "notes": project["notes"],
            }
        )

    return JSONResponse(
        {
            "ok": True,
            "date": selected_date.isoformat(),
            "items": items,
        }
    )


# -------------------- status + applications --------------------
@app.get("/api/line_status")
def line_status(request: Request, line_id: str) -> JSONResponse:
    user = _get_user(request)
    if not user:
        return JSONResponse(
            {
                "line_id": line_id,
                "auth_required": True,
                "applied": False,
                "count": 0,
                "latest": None,
            }
        )

    email = str(user.get("email") or "").strip().lower()

    try:
        if _use_postgres_read_backend():
            with PostgresAppQueries() as pg:
                rows = pg.list_line_status_applications(email, line_id)
        else:
            with get_db() as conn:
                rows = conn.execute(
                    """
                    SELECT a.application_id, a.submitted_at, a.status,
                           t.line_id, t.line_name, t.project_start, t.project_end, t.segment_id
                    FROM applications a
                    JOIN application_targets t ON t.application_id = a.application_id
                    WHERE lower(a.submitted_by_email) = ? AND ifnull(t.line_id, '') = ?
                    ORDER BY a.submitted_at DESC
                    """,
                    (email, line_id),
                ).fetchall()
    except Exception:
        return JSONResponse(
            {
                "line_id": line_id,
                "auth_required": False,
                "applied": False,
                "count": 0,
                "latest": None,
            }
        )

    if not rows:
        return JSONResponse(
            {
                "line_id": line_id,
                "auth_required": False,
                "applied": False,
                "count": 0,
                "latest": None,
            }
        )

    latest = rows[0]
    latest_summary = {
        "application_id": latest["application_id"],
        "submitted_at": latest["submitted_at"],
        "status": latest["status"],
        "event_start": latest["project_start"],
        "event_end": latest["project_end"],
        "context": {
            "segment_id": latest["segment_id"],
            "line_id": latest["line_id"],
            "line_name": latest["line_name"],
        },
    }

    return JSONResponse(
        {
            "line_id": line_id,
            "auth_required": False,
            "applied": True,
            "count": len(rows),
            "latest": latest_summary,
        }
    )


@app.get("/api/my_applications")
def my_applications(request: Request) -> JSONResponse:
    user = _require_user(request)
    email = str(user.get("email") or "").strip().lower()
    if _use_postgres_read_backend():
        try:
            with PostgresAppQueries() as pg:
                apps = pg.list_applications_for_email(email)
        except Exception as exc:
            raise _postgres_read_unavailable(exc)
    else:
        apps = _apps_for_email(email)

    out: List[Dict[str, Any]] = []
    for a in apps:
        out.append(
            {
                "application_id": a["application_id"],
                "submitted_at": a["submitted_at"],
                "status": a["status"],
                "person_mode": a.get("person_mode"),
                "decision_message": a.get("decision_message"),
                "work_details": a.get("work_details"),
                "contact_details": a.get("contact_details"),
                "targets": a.get("targets", []),
                "people": a.get("people", []),
                "uploads": a.get("uploads", []),
            }
        )

    return JSONResponse({"applications": out})


#----------------------admin_apply/view------------

@app.get("/api/tbgn/projects")
def api_list_tbgn_projects(request: Request) -> JSONResponse:
    _require_user(request)

    if _use_postgres_read_backend():
        try:
            with PostgresAppQueries() as pg:
                projects = pg.list_tbgn_projects(
                    limit=1000,
                    public=True,
                    published_only=True,
                )
        except Exception as exc:
            raise _postgres_read_unavailable(exc)
        return JSONResponse({"ok": True, "projects": projects})

    with get_db() as conn:
        rows = conn.execute(
            """
            SELECT *
            FROM tbgn_projects
            WHERE status = 'published'
            ORDER BY start_date ASC, end_date ASC, name ASC
            """
        ).fetchall()

    return JSONResponse(
        {
            "ok": True,
            "projects": [_tbgn_row_to_dict(row, public=True) for row in rows],
        }
    )


@app.get("/api/admin/tbgn")
def admin_list_tbgn_projects(request: Request) -> JSONResponse:
    _require_admin(request)

    if _use_postgres_read_backend():
        try:
            with PostgresAppQueries() as pg:
                projects = pg.list_tbgn_projects(limit=1000)
        except Exception as exc:
            raise _postgres_read_unavailable(exc)
        return JSONResponse({"ok": True, "projects": projects})

    with get_db() as conn:
        rows = conn.execute(
            """
            SELECT *
            FROM tbgn_projects
            ORDER BY start_date DESC, end_date DESC, updated_at DESC
            """
        ).fetchall()

    return JSONResponse(
        {
            "ok": True,
            "projects": [_tbgn_row_to_dict(row) for row in rows],
        }
    )


@app.get("/api/admin/tbgn/{project_id}")
def admin_get_tbgn_project(project_id: str, request: Request) -> JSONResponse:
    _require_admin(request)

    if _use_postgres_read_backend():
        try:
            with PostgresAppQueries() as pg:
                project = pg.get_tbgn_project(project_id)
        except Exception as exc:
            raise _postgres_read_unavailable(exc)
        if not project:
            raise HTTPException(status_code=404, detail="TBGN project not found.")
        return JSONResponse({"ok": True, "project": project})

    with get_db() as conn:
        row = conn.execute(
            "SELECT * FROM tbgn_projects WHERE id = ?",
            (project_id,),
        ).fetchone()

    if not row:
        raise HTTPException(status_code=404, detail="TBGN project not found.")

    return JSONResponse({"ok": True, "project": _tbgn_row_to_dict(row)})


@app.post("/api/admin/tbgn")
async def admin_create_tbgn_project(request: Request) -> JSONResponse:
    user = _require_admin(request)
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Request body must be valid JSON.")

    if not isinstance(body, dict):
        raise HTTPException(status_code=400, detail="Request body must be a JSON object.")

    payload = _validate_tbgn_payload(body)
    project_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()
    created_by = str(user.get("email") or "").strip().lower()

    if _use_postgres_read_backend():
        try:
            with PostgresAppQueries() as pg:
                project = pg.create_tbgn_project(
                    project_id=project_id,
                    payload=payload,
                    created_by=created_by,
                    created_at=now,
                )
                write_audit_log(
                    actor_email=created_by,
                    actor_type="admin",
                    action_scope="admin_action",
                    action="tbgn_project_created",
                    entity_type="tbgn_project",
                    entity_id=project_id,
                    new_value={"status": project.get("status"), "name": project.get("name")},
                    metadata={"project_id": project_id},
                    request=request,
                    conn=pg._conn(),
                )
        except Exception as exc:
            raise _postgres_read_unavailable(exc)
        return JSONResponse({"ok": True, "project": project})

    with get_db() as conn:
        conn.execute(
            """
            INSERT INTO tbgn_projects (
                id, name, start_date, end_date, affected_lines, color, geometry,
                status, notes, created_by, created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                project_id,
                payload["name"],
                payload["start_date"],
                payload["end_date"],
                payload["affected_lines"],
                payload["color"],
                payload["geometry"],
                payload["status"],
                payload["notes"],
                created_by,
                now,
                now,
            ),
        )
        row = conn.execute(
            "SELECT * FROM tbgn_projects WHERE id = ?",
            (project_id,),
        ).fetchone()

    return JSONResponse({"ok": True, "project": _tbgn_row_to_dict(row)})


@app.put("/api/admin/tbgn/{project_id}")
async def admin_update_tbgn_project(project_id: str, request: Request) -> JSONResponse:
    user = _require_admin(request)
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Request body must be valid JSON.")

    if not isinstance(body, dict):
        raise HTTPException(status_code=400, detail="Request body must be a JSON object.")

    if _use_postgres_read_backend():
        try:
            with PostgresAppQueries() as pg:
                with pg._conn().transaction():
                    existing = pg.get_tbgn_project(project_id)
                    if not existing:
                        raise HTTPException(status_code=404, detail="TBGN project not found.")
                    payload = _validate_tbgn_payload(body, existing=existing)
                    now = datetime.now(timezone.utc).isoformat()
                    project = pg.update_tbgn_project(project_id, payload=payload, updated_at=now)
                    if project:
                        write_audit_log(
                            actor_email=str(user.get("email") or "").strip().lower(),
                            actor_type="admin",
                            action_scope="admin_action",
                            action="tbgn_project_updated",
                            entity_type="tbgn_project",
                            entity_id=project_id,
                            old_value={"status": existing.get("status"), "name": existing.get("name")},
                            new_value={"status": project.get("status"), "name": project.get("name")},
                            metadata={"project_id": project_id},
                            request=request,
                            conn=pg._conn(),
                        )
        except HTTPException:
            raise
        except Exception as exc:
            raise _postgres_read_unavailable(exc)
        if not project:
            raise HTTPException(status_code=404, detail="TBGN project not found.")
        return JSONResponse({"ok": True, "project": project})

    with get_db() as conn:
        existing = conn.execute(
            "SELECT * FROM tbgn_projects WHERE id = ?",
            (project_id,),
        ).fetchone()

        if not existing:
            raise HTTPException(status_code=404, detail="TBGN project not found.")

        payload = _validate_tbgn_payload(body, existing=existing)
        now = datetime.now(timezone.utc).isoformat()

        conn.execute(
            """
            UPDATE tbgn_projects
            SET name = ?,
                start_date = ?,
                end_date = ?,
                affected_lines = ?,
                color = ?,
                geometry = ?,
                status = ?,
                notes = ?,
                updated_at = ?
            WHERE id = ?
            """,
            (
                payload["name"],
                payload["start_date"],
                payload["end_date"],
                payload["affected_lines"],
                payload["color"],
                payload["geometry"],
                payload["status"],
                payload["notes"],
                now,
                project_id,
            ),
        )
        row = conn.execute(
            "SELECT * FROM tbgn_projects WHERE id = ?",
            (project_id,),
        ).fetchone()

    return JSONResponse({"ok": True, "project": _tbgn_row_to_dict(row)})


@app.delete("/api/admin/tbgn/{project_id}")
async def admin_delete_tbgn_project(project_id: str, request: Request) -> JSONResponse:
    user = _require_admin(request)

    if _use_postgres_read_backend():
        try:
            with PostgresAppQueries() as pg:
                with pg._conn().transaction():
                    existing = pg.get_tbgn_project(project_id)
                    if not existing:
                        raise HTTPException(status_code=404, detail="TBGN project not found.")
                    deleted = pg.delete_tbgn_project(project_id)
                    if deleted:
                        write_audit_log(
                            actor_email=str(user.get("email") or "").strip().lower(),
                            actor_type="admin",
                            action_scope="admin_action",
                            action="tbgn_project_deleted",
                            entity_type="tbgn_project",
                            entity_id=project_id,
                            old_value={"status": existing.get("status"), "name": existing.get("name")},
                            metadata={"deleted_entity_id": project_id},
                            request=request,
                            conn=pg._conn(),
                        )
        except HTTPException:
            raise
        except Exception as exc:
            raise _postgres_read_unavailable(exc)
        if not deleted:
            raise HTTPException(status_code=404, detail="TBGN project not found.")
        return JSONResponse({"ok": True, "id": project_id})

    with get_db() as conn:
        row = conn.execute(
            "SELECT id FROM tbgn_projects WHERE id = ?",
            (project_id,),
        ).fetchone()

        if not row:
            raise HTTPException(status_code=404, detail="TBGN project not found.")

        conn.execute(
            "DELETE FROM tbgn_projects WHERE id = ?",
            (project_id,),
        )

    return JSONResponse({"ok": True, "id": project_id})


@app.get("/api/admin/applications")
def admin_list_applications(
    request: Request,
    status: Optional[str] = None,
    email: Optional[str] = None,
) -> JSONResponse:
    _require_admin(request)

    if _use_postgres_read_backend():
        try:
            with PostgresAppQueries() as pg:
                applications = pg.list_applications(
                    status=status,
                    email=email,
                    limit=1000,
                )
        except Exception as exc:
            raise _postgres_read_unavailable(exc)
        return JSONResponse({"applications": applications})

    query = """
        SELECT *
        FROM applications
        WHERE 1=1
    """
    params: List[Any] = []

    if status:
        query += " AND status = ?"
        params.append(status.strip())

    if email:
        query += " AND lower(submitted_by_email) LIKE ?"
        params.append(f"%{email.strip().lower()}%")

    query += " ORDER BY submitted_at DESC"

    with get_db() as conn:
        rows = conn.execute(query, params).fetchall()

    return JSONResponse(
        {
            "applications": [_admin_application_row_to_summary(r) for r in rows]
        }
    )


@app.get("/api/admin/applications/{application_id}")
def admin_get_application(application_id: str, request: Request) -> JSONResponse:
    _require_admin(request)

    if _use_postgres_read_backend():
        try:
            with PostgresAppQueries() as pg:
                data = pg.get_application_detail(application_id)
        except Exception as exc:
            raise _postgres_read_unavailable(exc)
        if not data:
            raise HTTPException(status_code=404, detail="Application not found.")
        return JSONResponse(data)

    with get_db() as conn:
        row = conn.execute(
            "SELECT * FROM applications WHERE application_id = ?",
            (application_id,),
        ).fetchone()

        if not row:
            raise HTTPException(status_code=404, detail="Application not found.")

        data = _serialize_application_summary(conn, row)

    return JSONResponse(data)


@app.post("/api/admin/applications/{application_id}/status")
async def admin_update_application_status(application_id: str, request: Request) -> JSONResponse:
    user = _require_admin(request)

    body = await request.json()
    new_status = str(body.get("status") or "").strip().lower()
    admin_note = str(body.get("admin_note") or "").strip()
    decision_message = str(body.get("decision_message") or "").strip()

    allowed = {"submitted", "approved", "rejected"}
    if new_status not in allowed:
        raise HTTPException(status_code=400, detail="Invalid status.")

    # Optional behavior:
    # when reset to submitted, clear the user-facing decision message
    if new_status == "submitted":
        decision_message = ""

    if _use_postgres_read_backend():
        try:
            with PostgresAppQueries() as pg:
                with pg._conn().transaction():
                    existing = pg.get_application_detail(application_id)
                    if not existing:
                        raise HTTPException(status_code=404, detail="Application not found.")
                    updated = pg.update_application_status(
                        application_id=application_id,
                        status=new_status,
                        admin_note=admin_note,
                        decision_message=decision_message,
                    )
                    if updated:
                        write_audit_log(
                            actor_email=str(user.get("email") or "").strip().lower(),
                            actor_type="admin",
                            action_scope="admin_action",
                            action="application_status_changed",
                            entity_type="application",
                            entity_id=application_id,
                            old_value={"status": existing.get("status")},
                            new_value={"status": new_status},
                            metadata={"application_id": application_id},
                            request=request,
                            conn=pg._conn(),
                        )
        except HTTPException:
            raise
        except Exception as exc:
            raise _postgres_read_unavailable(exc)
        if not updated:
            raise HTTPException(status_code=404, detail="Application not found.")
        return JSONResponse(
            {
                "ok": True,
                "application_id": application_id,
                "status": new_status,
                "admin_note": admin_note,
                "decision_message": decision_message,
            }
        )

    with get_db() as conn:
        row = conn.execute(
            "SELECT application_id FROM applications WHERE application_id = ?",
            (application_id,),
        ).fetchone()

        if not row:
            raise HTTPException(status_code=404, detail="Application not found.")

        conn.execute(
            """
            UPDATE applications
            SET status = ?, admin_note = ?, decision_message = ?
            WHERE application_id = ?
            """,
            (new_status, admin_note, decision_message, application_id),
        )

    return JSONResponse(
        {
            "ok": True,
            "application_id": application_id,
            "status": new_status,
            "admin_note": admin_note,
            "decision_message": decision_message,
        }
    )


@app.get("/api/admin/uploads/{stored_filename}")
def admin_download_upload(stored_filename: str, request: Request) -> FileResponse:
    _require_admin(request)

    safe_name = Path(stored_filename).name
    file_path = UPLOADS_DIR / safe_name

    if not file_path.exists() or not file_path.is_file():
        raise HTTPException(status_code=404, detail="File not found.")

    return FileResponse(file_path, filename=safe_name)


@app.delete("/api/admin/applications/{application_id}")
async def admin_delete_application(application_id: str, request: Request) -> JSONResponse:
    user = _require_admin(request)

    if _use_postgres_read_backend():
        try:
            with PostgresAppQueries() as pg:
                with pg._conn().transaction():
                    existing = pg.get_application_detail(application_id)
                    if not existing:
                        raise HTTPException(status_code=404, detail="Application not found.")
                    uploads = pg.get_application_upload_filenames(application_id)
                    deleted = pg.delete_application(application_id)
                    if deleted:
                        write_audit_log(
                            actor_email=str(user.get("email") or "").strip().lower(),
                            actor_type="admin",
                            action_scope="admin_action",
                            action="application_deleted",
                            entity_type="application",
                            entity_id=application_id,
                            old_value={"status": existing.get("status")},
                            metadata={"deleted_entity_id": application_id, "upload_count": len(uploads)},
                            request=request,
                            conn=pg._conn(),
                        )
        except HTTPException:
            raise
        except Exception as exc:
            raise _postgres_read_unavailable(exc)

        if not deleted:
            raise HTTPException(status_code=404, detail="Application not found.")

        for stored_filename in uploads:
            file_path = UPLOADS_DIR / Path(stored_filename).name
            if file_path.exists():
                file_path.unlink()

        return JSONResponse({"ok": True, "deleted": application_id})

    with get_db() as conn:
        row = conn.execute(
            "SELECT application_id FROM applications WHERE application_id = ?",
            (application_id,),
        ).fetchone()

        if not row:
            raise HTTPException(status_code=404, detail="Application not found.")

        # Clean up uploaded files from disk
        uploads = conn.execute(
            "SELECT stored_filename FROM application_uploads WHERE application_id = ?",
            (application_id,),
        ).fetchall()

        for u in uploads:
            file_path = UPLOADS_DIR / u["stored_filename"]
            if file_path.exists():
                file_path.unlink()

        # CASCADE deletes targets, people, uploads rows automatically
        conn.execute(
            "DELETE FROM applications WHERE application_id = ?",
            (application_id,),
        )

    return JSONResponse({"ok": True, "deleted": application_id})


# -------------------- apply --------------------
@app.post("/api/apply")
async def apply_for_project(
    request: Request,
    payload_json: str = Form(...),
    safety_plans: List[UploadFile] = File(...),
) -> JSONResponse:
    user = _require_user(request)
    session_email = str(user.get("email") or "").strip().lower()

    if not _ensure_user_exists(session_email):
        raise HTTPException(status_code=401, detail="Logged-in account no longer exists.")

    payload = _parse_json_field(payload_json, "payload_json")

    targets = payload.get("targets") or []
    person_mode = str(payload.get("person_mode") or "").strip()
    shared_person = payload.get("shared_person") or {}
    people_by_target = payload.get("people_by_target") or []
    raw_work_details = payload.get("work_details") or {}
    raw_contact_details = payload.get("contact_details") or {}
    work_details = raw_work_details if isinstance(raw_work_details, dict) else {}
    contact_details = raw_contact_details if isinstance(raw_contact_details, dict) else {}
    validated_work_details = {
        "description": str(work_details.get("description") or "").strip() or None,
        "source": str(work_details.get("source") or "").strip() or None,
        "urgency": str(work_details.get("urgency") or "").strip() or None,
        "affected_lines": str(work_details.get("affected_lines") or "").strip() or None,
        "notes": str(work_details.get("notes") or "").strip() or None,
    }
    validated_contact_details = {
        "coordinator": str(contact_details.get("coordinator") or "").strip() or None,
        "vvw_measure": str(contact_details.get("vvw_measure") or "").strip() or None,
    }

    if not isinstance(targets, list) or not targets:
        raise HTTPException(status_code=400, detail="At least one target is required.")
    if len(targets) > 3:
        raise HTTPException(status_code=400, detail="Maximum 3 targets allowed.")

    if person_mode not in {"single", "per-segment"}:
        raise HTTPException(status_code=400, detail="person_mode must be 'single' or 'per-segment'.")

    if not safety_plans:
        raise HTTPException(status_code=400, detail="At least one safety plan file is required.")
    if len(safety_plans) > MAX_UPLOAD_FILES:
        raise HTTPException(
            status_code=400,
            detail=f"Maximum {MAX_UPLOAD_FILES} safety plan files are allowed.",
        )

    min_start = date.today() + timedelta(days=28)

    validated_targets: List[Dict[str, Any]] = []
    max_schedule_windows = 8

    for idx, target in enumerate(targets):
        work_mode = str(target.get("work_mode") or "").strip()
        if work_mode not in {"whole-segment", "custom-area"}:
            raise HTTPException(status_code=400, detail=f"Target {idx + 1}: invalid work_mode.")

        try:
            target_type = _normalize_application_target_type(target.get("target_type"))
        except HTTPException:
            raise HTTPException(status_code=400, detail=f"Target {idx + 1}: invalid target_type.")

        segment_id = str(target.get("segment_id") or "").strip()
        asset_id = str(target.get("asset_id") or "").strip()
        if not asset_id and target_type == "rail_segment":
            asset_id = segment_id
        if not asset_id and segment_id:
            asset_id = segment_id
        if not asset_id:
            raise HTTPException(status_code=400, detail=f"Target {idx + 1}: asset_id or segment_id is required.")

        asset_label = str(target.get("asset_label") or "").strip() or _default_asset_label(
            target_type,
            asset_id,
            segment_id,
        )
        asset_source = str(target.get("asset_source") or "").strip() or _default_asset_source(target_type)
        line_id = str(target.get("line_id") or "").strip()
        line_name = str(target.get("line_name") or "").strip()

        raw_schedules = target.get("schedules")
        validated_schedules: List[Dict[str, Any]] = []

        if raw_schedules is not None:
            if not isinstance(raw_schedules, list):
                raise HTTPException(status_code=400, detail=f"Target {idx + 1}: schedules must be a list.")
            if not raw_schedules:
                raise HTTPException(status_code=400, detail=f"Target {idx + 1}: at least one schedule window is required.")
            if len(raw_schedules) > max_schedule_windows:
                raise HTTPException(
                    status_code=400,
                    detail=f"Target {idx + 1}: maximum {max_schedule_windows} schedule windows allowed.",
                )

            for schedule_index, schedule in enumerate(raw_schedules):
                if not isinstance(schedule, dict):
                    raise HTTPException(
                        status_code=400,
                        detail=f"Target {idx + 1}, window {schedule_index + 1}: invalid schedule format.",
                    )

                project_start = str(schedule.get("project_start") or "").strip()
                project_end = str(schedule.get("project_end") or "").strip()
                schedule_label = str(schedule.get("label") or "").strip() or "Custom work"

                try:
                    start_dt = datetime.fromisoformat(project_start)
                    end_dt = datetime.fromisoformat(project_end)
                except Exception:
                    raise HTTPException(
                        status_code=400,
                        detail=f"Target {idx + 1}, window {schedule_index + 1}: invalid project_start/project_end.",
                    )

                if end_dt <= start_dt:
                    raise HTTPException(
                        status_code=400,
                        detail=f"Target {idx + 1}, window {schedule_index + 1}: project_end must be after project_start.",
                    )

                if start_dt.date() < min_start:
                    raise HTTPException(
                        status_code=400,
                        detail=f"Target {idx + 1}, window {schedule_index + 1}: start must be at least 4 weeks from today.",
                    )

                validated_schedules.append(
                    {
                        "project_start": project_start,
                        "project_end": project_end,
                        "label": schedule_label,
                    }
                )
        else:
            project_start = str(target.get("project_start") or "").strip()
            project_end = str(target.get("project_end") or "").strip()

            try:
                start_dt = datetime.fromisoformat(project_start)
                end_dt = datetime.fromisoformat(project_end)
            except Exception:
                raise HTTPException(status_code=400, detail=f"Target {idx + 1}: invalid project_start/project_end.")

            if end_dt <= start_dt:
                raise HTTPException(status_code=400, detail=f"Target {idx + 1}: project_end must be after project_start.")

            if start_dt.date() < min_start:
                raise HTTPException(
                    status_code=400,
                    detail=f"Target {idx + 1}: start must be at least 4 weeks from today.",
                )

            validated_schedules.append(
                {
                    "project_start": project_start,
                    "project_end": project_end,
                    "label": "Custom work",
                }
            )

        first_schedule = validated_schedules[0]

        if work_mode == "custom-area":
            if target.get("work_start_point") is None or target.get("work_end_point") is None:
                raise HTTPException(
                    status_code=400,
                    detail=f"Target {idx + 1}: custom-area requires start and end points.",
                )

        validated_targets.append(
            {
                "target_type": target_type,
                "asset_id": asset_id,
                "asset_label": asset_label,
                "asset_source": asset_source,
                "segment_id": segment_id,
                "line_id": line_id,
                "line_name": line_name,
                "work_mode": work_mode,
                "work_start_point": target.get("work_start_point"),
                "work_end_point": target.get("work_end_point"),
                "project_start": first_schedule["project_start"],
                "project_end": first_schedule["project_end"],
                "schedules": validated_schedules,
            }
        )

    if person_mode == "single":
        required = ["first_name", "last_name", "phone", "email"]
        for key in required:
            if not str(shared_person.get(key) or "").strip():
                raise HTTPException(status_code=400, detail=f"Shared person missing {key}.")
    else:
        if not isinstance(people_by_target, list) or len(people_by_target) != len(validated_targets):
            raise HTTPException(status_code=400, detail="people_by_target must match targets length.")
        for idx, person in enumerate(people_by_target):
            for key in ["first_name", "last_name", "phone", "email"]:
                if not str(person.get(key) or "").strip():
                    raise HTTPException(status_code=400, detail=f"Target {idx + 1} person missing {key}.")

    if person_mode == "single":
        people_records = [
            {
                "target_index": None,
                "first_name": str(shared_person.get("first_name") or "").strip(),
                "last_name": str(shared_person.get("last_name") or "").strip(),
                "phone": str(shared_person.get("phone") or "").strip(),
                "email": str(shared_person.get("email") or "").strip(),
                "employee_id": str(shared_person.get("employee_id") or "").strip() or None,
            }
        ]
    else:
        people_records = [
            {
                "target_index": idx,
                "first_name": str(person.get("first_name") or "").strip(),
                "last_name": str(person.get("last_name") or "").strip(),
                "phone": str(person.get("phone") or "").strip(),
                "email": str(person.get("email") or "").strip(),
                "employee_id": str(person.get("employee_id") or "").strip() or None,
            }
            for idx, person in enumerate(people_by_target)
        ]

    def raise_conflict(idx: int, schedule_index: int, schedule: Dict[str, Any], conflict: Dict[str, Any]) -> None:
        requested_label = schedule.get("label") or "Custom work"
        existing_schedule_label = conflict.get("schedule_label") or "Custom work"
        existing_schedule_index = conflict.get("schedule_index")
        existing_schedule_text = (
            f"window {int(existing_schedule_index) + 1}"
            if existing_schedule_index is not None
            else "fallback window"
        )
        raise HTTPException(
            status_code=409,
            detail=(
                f"Target {idx + 1}, window {schedule_index + 1} ({requested_label}) conflicts with "
                f"an existing booking for {conflict['asset_label'] or conflict['line_name'] or conflict['line_id'] or '-'} "
                f"({conflict['target_type']} {conflict['asset_id']}, {existing_schedule_text}: {existing_schedule_label}) "
                f"from {conflict['project_start']} to {conflict['project_end']}."
            ),
        )

    if _use_postgres_read_backend():
        try:
            with PostgresAppQueries() as pg:
                for idx, target in enumerate(validated_targets):
                    target_type = target["target_type"]
                    asset_id = target["asset_id"]
                    if not asset_id:
                        continue

                    schedules = target.get("schedules") or []
                    for schedule_index, schedule in enumerate(schedules):
                        conflict = pg.find_asset_conflict(
                            target_type=target_type,
                            asset_id=asset_id,
                            project_start=schedule["project_start"],
                            project_end=schedule["project_end"],
                        )
                        if conflict:
                            raise_conflict(idx, schedule_index, schedule, conflict)
        except HTTPException:
            raise
        except Exception as exc:
            raise _postgres_read_unavailable(exc)
    else:
        with get_db() as conn:
            for idx, target in enumerate(validated_targets):
                target_type = target["target_type"]
                asset_id = target["asset_id"]
                if not asset_id:
                    continue

                schedules = target.get("schedules") or []
                for schedule_index, schedule in enumerate(schedules):
                    conflict = _find_asset_conflict(
                        conn=conn,
                        target_type=target_type,
                        asset_id=asset_id,
                        project_start=schedule["project_start"],
                        project_end=schedule["project_end"],
                    )

                    if conflict:
                        raise_conflict(idx, schedule_index, schedule, conflict)

    saved_files: List[Dict[str, str]] = []
    app_id = str(uuid.uuid4())
    now_iso = datetime.now(timezone.utc).isoformat()

    for f in safety_plans:
        saved_files.append(await _save_validated_upload(f, app_id))

    try:
        if _use_postgres_read_backend():
            try:
                with PostgresAppQueries() as pg:
                    pg.create_application(
                        application_id=app_id,
                        submitted_at=now_iso,
                        submitted_by_email=session_email,
                        person_mode=person_mode,
                        work_details=validated_work_details,
                        contact_details=validated_contact_details,
                        targets=validated_targets,
                        people=people_records,
                        uploads=saved_files,
                    )
                    write_audit_log(
                        actor_email=session_email,
                        actor_type="user",
                        action_scope="user_action",
                        action="application_submitted",
                        entity_type="application",
                        entity_id=app_id,
                        new_value={"status": "submitted"},
                        metadata={
                            "application_id": app_id,
                            "target_count": len(validated_targets),
                            "upload_count": len(saved_files),
                        },
                        request=request,
                        conn=pg._conn(),
                    )
                    if saved_files:
                        write_audit_log(
                            actor_email=session_email,
                            actor_type="user",
                            action_scope="user_action",
                            action="file_upload_metadata_saved",
                            entity_type="application",
                            entity_id=app_id,
                            metadata={
                                "application_id": app_id,
                                "file_count": len(saved_files),
                            },
                            request=request,
                            conn=pg._conn(),
                        )
            except Exception as exc:
                raise _postgres_read_unavailable(exc)
            return JSONResponse({"ok": True, "application_id": app_id})

        with get_db() as conn:
            conn.execute(
                """
                INSERT INTO applications (
                    application_id, submitted_at, status, submitted_by_email, person_mode,
                    work_description, work_source, urgency, affected_lines, work_notes,
                    coordinator, vvw_measure
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    app_id,
                    now_iso,
                    "submitted",
                    session_email,
                    person_mode,
                    validated_work_details["description"],
                    validated_work_details["source"],
                    validated_work_details["urgency"],
                    validated_work_details["affected_lines"],
                    validated_work_details["notes"],
                    validated_contact_details["coordinator"],
                    validated_contact_details["vvw_measure"],
                ),
            )

            for idx, target in enumerate(validated_targets):
                wsp = target.get("work_start_point") or {}
                wep = target.get("work_end_point") or {}

                target_cursor = conn.execute(
                    """
                    INSERT INTO application_targets (
                        application_id, target_index, target_type, asset_id, asset_label, asset_source,
                        segment_id, line_id, line_name,
                        work_mode, work_start_x, work_start_y, work_end_x, work_end_y,
                        project_start, project_end
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        app_id,
                        idx,
                        target["target_type"],
                        target["asset_id"] or None,
                        target["asset_label"] or None,
                        target["asset_source"] or None,
                        target["segment_id"] or None,
                        target["line_id"] or None,
                        target["line_name"] or None,
                        target["work_mode"],
                        wsp.get("x"),
                        wsp.get("y"),
                        wep.get("x"),
                        wep.get("y"),
                        target["project_start"],
                        target["project_end"],
                    ),
                )
                target_row_id = target_cursor.lastrowid

                schedules = target.get("schedules") or []
                for schedule_index, schedule in enumerate(schedules):
                    conn.execute(
                        """
                        INSERT INTO application_target_windows (
                            target_id, window_index, project_start, project_end, label
                        )
                        VALUES (?, ?, ?, ?, ?)
                        """,
                        (
                            target_row_id,
                            schedule_index,
                            schedule.get("project_start"),
                            schedule.get("project_end"),
                            schedule.get("label") or "Custom work",
                        ),
                    )

            if person_mode == "single":
                conn.execute(
                    """
                    INSERT INTO application_people (
                        application_id, target_index, first_name, last_name, phone, email, employee_id
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        app_id,
                        None,
                        str(shared_person.get("first_name") or "").strip(),
                        str(shared_person.get("last_name") or "").strip(),
                        str(shared_person.get("phone") or "").strip(),
                        str(shared_person.get("email") or "").strip(),
                        str(shared_person.get("employee_id") or "").strip() or None,
                    ),
                )
            else:
                for idx, person in enumerate(people_by_target):
                    conn.execute(
                        """
                        INSERT INTO application_people (
                            application_id, target_index, first_name, last_name, phone, email, employee_id
                        )
                        VALUES (?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            app_id,
                            idx,
                            str(person.get("first_name") or "").strip(),
                            str(person.get("last_name") or "").strip(),
                            str(person.get("phone") or "").strip(),
                            str(person.get("email") or "").strip(),
                            str(person.get("employee_id") or "").strip() or None,
                        ),
                    )

            for item in saved_files:
                conn.execute(
                    """
                    INSERT INTO application_uploads (
                        application_id, original_filename, stored_filename, created_at
                    )
                    VALUES (?, ?, ?, ?)
                    """,
                    (
                        app_id,
                        item["filename"],
                        item["stored_filename"],
                        now_iso,
                    ),
                )
    except Exception:
        _delete_saved_uploads(saved_files)
        raise

    return JSONResponse({"ok": True, "application_id": app_id})

#-----------------------------LIST-VIEW------------------------------------
@app.get("/list-view")
def list_view(request: Request) -> FileResponse:
    _require_user(request)
    return FileResponse(STATIC_DIR / "list_view" / "list-view.html")


#-----------------------------RETURN_SEGMENT_VIEWS-------------------------

@app.get("/api/segment_bookings")
def segment_bookings(
    request: Request,
    week_start: str,
    segment_id: Optional[str] = None,
    target_type: Optional[str] = "rail_segment",
    asset_id: Optional[str] = None,
) -> JSONResponse:
    _require_user(request)

    try:
        week_start_d = date.fromisoformat(week_start)
    except Exception:
        raise HTTPException(status_code=400, detail="week_start must be YYYY-MM-DD")

    try:
        resolved_target_type = _normalize_application_target_type(target_type)
    except HTTPException:
        raise HTTPException(status_code=400, detail="Invalid target_type.")

    resolved_asset_id = str(asset_id or "").strip()
    resolved_segment_id = str(segment_id or "").strip()
    if not resolved_asset_id:
        resolved_asset_id = resolved_segment_id
    if not resolved_asset_id:
        raise HTTPException(status_code=400, detail="asset_id or segment_id is required.")

    week_end_d = week_start_d + timedelta(days=7)

    week_start_dt = datetime.combine(week_start_d, datetime.min.time()).isoformat()
    week_end_dt = datetime.combine(week_end_d, datetime.min.time()).isoformat()

    if _use_postgres_read_backend():
        try:
            with PostgresAppQueries() as pg:
                rows = pg.list_segment_bookings(
                    target_type=resolved_target_type,
                    asset_id=resolved_asset_id,
                    range_start=week_start_dt,
                    range_end=week_end_dt,
                )
        except Exception as exc:
            raise _postgres_read_unavailable(exc)
    else:
        with get_db() as conn:
            rows = conn.execute(
                """
                SELECT
                    a.status,
                    coalesce(nullif(t.target_type, ''), 'rail_segment') AS target_type,
                    coalesce(nullif(t.asset_id, ''), t.segment_id, '') AS asset_id,
                    t.asset_label,
                    t.asset_source,
                    t.segment_id,
                    t.line_id,
                    t.line_name,
                    coalesce(w.project_start, t.project_start) AS project_start,
                    coalesce(w.project_end, t.project_end) AS project_end,
                    w.label AS schedule_label,
                    w.window_index AS schedule_index
                FROM applications a
                JOIN application_targets t
                  ON t.application_id = a.application_id
                LEFT JOIN application_target_windows w
                  ON w.target_id = t.id
                WHERE coalesce(nullif(t.target_type, ''), 'rail_segment') = ?
                  AND coalesce(nullif(t.asset_id, ''), t.segment_id, '') = ?
                  AND coalesce(w.project_start, t.project_start) < ?
                  AND coalesce(w.project_end, t.project_end) > ?
                ORDER BY coalesce(w.project_start, t.project_start) ASC
                """,
                (resolved_target_type, resolved_asset_id, week_end_dt, week_start_dt),
            ).fetchall()

    bookings = []
    for row in rows:
        bookings.append(
            {
                "status": row["status"],
                "target_type": row["target_type"],
                "asset_id": row["asset_id"],
                "asset_label": row["asset_label"] or _default_asset_label(
                    row["target_type"],
                    row["asset_id"],
                    row["segment_id"] or "",
                ),
                "asset_source": row["asset_source"] or _default_asset_source(row["target_type"]),
                "segment_id": row["segment_id"],
                "line_id": row["line_id"],
                "line_name": row["line_name"],
                "project_start": row["project_start"],
                "project_end": row["project_end"],
                "schedule_label": row["schedule_label"] or "Custom work",
                "schedule_index": row["schedule_index"],
            }
        )

    return JSONResponse({"bookings": bookings})


# -------------------- Transfer Trip endpoints --------------------
@app.get("/api/transfer/stops")
def api_transfer_stops(request: Request) -> JSONResponse:
    _require_user(request)
    stops = [
        {
            "id": info["id"],
            "name": info["name"],
            "coordinates": info["coordinates"],
        }
        for info in _HALTES_SNAPPED.values()
    ]
    stops.sort(key=lambda s: s["name"])
    return JSONResponse({"ok": True, "stops": stops, "count": len(stops)})


@app.post("/api/transfer/route")
async def api_transfer_route(request: Request) -> JSONResponse:
    _require_user(request)
    body = await request.json()
    start_stop_id = body.get("start_stop_id")
    end_stop_id = body.get("end_stop_id")

    if start_stop_id is None or end_stop_id is None:
        raise HTTPException(status_code=400, detail="start_stop_id and end_stop_id are required.")

    try:
        start_stop_id = int(start_stop_id)
        end_stop_id = int(end_stop_id)
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="Stop IDs must be integers.")

    route = _compute_transfer_route(start_stop_id, end_stop_id)
    return JSONResponse({"ok": True, "route": route})


@app.post("/api/transfer/apply")
async def api_transfer_apply(request: Request) -> JSONResponse:
    user = _require_user(request)
    session_email = str(user.get("email") or "").strip().lower()

    if not _ensure_user_exists(session_email):
        raise HTTPException(status_code=401, detail="Logged-in account no longer exists.")

    body = await request.json()

    start_stop_id = body.get("start_stop_id")
    end_stop_id = body.get("end_stop_id")
    planned_date = str(body.get("planned_date") or "").strip()
    planned_start_time = str(body.get("planned_start_time") or "").strip()
    planned_end_time = str(body.get("planned_end_time") or "").strip()
    tram_number = str(body.get("tram_number") or "").strip() or None
    reason = str(body.get("reason") or "").strip() or None
    notes = str(body.get("notes") or "").strip() or None

    if start_stop_id is None or end_stop_id is None:
        raise HTTPException(status_code=400, detail="start_stop_id and end_stop_id are required.")

    try:
        start_stop_id = int(start_stop_id)
        end_stop_id = int(end_stop_id)
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="Stop IDs must be integers.")

    if not planned_date:
        raise HTTPException(status_code=400, detail="planned_date is required.")
    if not planned_start_time or not planned_end_time:
        raise HTTPException(status_code=400, detail="planned_start_time and planned_end_time are required.")

    parsed_date = _parse_iso_date_safe(planned_date)
    if not parsed_date:
        raise HTTPException(status_code=400, detail="planned_date must be YYYY-MM-DD.")

    min_date = date.today() + timedelta(days=7)
    if parsed_date < min_date:
        raise HTTPException(
            status_code=400,
            detail="planned_date must be at least 1 week from today.",
        )

    route = _compute_transfer_route(start_stop_id, end_stop_id)

    trip_id = str(uuid.uuid4())
    now_iso = datetime.now(timezone.utc).isoformat()
    coords = route["geometry"]["coordinates"] or []

    if _use_postgres_read_backend():
        points = [
            {
                "point_index": idx,
                "segment_id": None,
                "lng": coord[0],
                "lat": coord[1],
            }
            for idx, coord in enumerate(coords)
        ]
        try:
            with PostgresAppQueries() as pg:
                pg.create_transfer_trip(
                    transfer_trip_id=trip_id,
                    submitted_at=now_iso,
                    submitted_by_email=session_email,
                    start_stop_id=start_stop_id,
                    start_stop_name=route["start_stop"]["name"],
                    end_stop_id=end_stop_id,
                    end_stop_name=route["end_stop"]["name"],
                    planned_date=planned_date,
                    planned_start_time=planned_start_time,
                    planned_end_time=planned_end_time,
                    tram_number=tram_number,
                    reason=reason,
                    notes=notes,
                    route_distance_m=route["distance_m"],
                    route_geometry=route["geometry"],
                    points=points,
                )
                write_audit_log(
                    actor_email=session_email,
                    actor_type="user",
                    action_scope="user_action",
                    action="transfer_trip_submitted",
                    entity_type="transfer_trip",
                    entity_id=trip_id,
                    new_value={"status": "submitted"},
                    metadata={
                        "transfer_trip_id": trip_id,
                        "start_stop_id": start_stop_id,
                        "end_stop_id": end_stop_id,
                        "point_count": len(points),
                    },
                    request=request,
                    conn=pg._conn(),
                )
        except Exception as exc:
            raise _postgres_read_unavailable(exc)
        return JSONResponse({"ok": True, "transfer_trip_id": trip_id})

    with get_db() as conn:
        conn.execute(
            """
            INSERT INTO transfer_trips (
                transfer_trip_id, submitted_at, status, submitted_by_email,
                start_stop_id, start_stop_name, end_stop_id, end_stop_name,
                planned_date, planned_start_time, planned_end_time,
                tram_number, reason, notes,
                route_distance_m, route_geometry
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                trip_id, now_iso, "submitted", session_email,
                start_stop_id, route["start_stop"]["name"],
                end_stop_id, route["end_stop"]["name"],
                planned_date, planned_start_time, planned_end_time,
                tram_number, reason, notes,
                route["distance_m"],
                json.dumps(route["geometry"]),
            ),
        )

        for idx, coord in enumerate(coords):
            conn.execute(
                """
                INSERT INTO transfer_trip_points (
                    transfer_trip_id, point_index, segment_id, lng, lat
                )
                VALUES (?, ?, ?, ?, ?)
                """,
                (trip_id, idx, None, coord[0], coord[1]),
            )

    return JSONResponse({"ok": True, "transfer_trip_id": trip_id})


def _serialize_transfer_trip(row: sqlite3.Row) -> Dict[str, Any]:
    route_geometry = None
    raw_geom = row["route_geometry"]
    if raw_geom:
        try:
            route_geometry = json.loads(raw_geom)
        except Exception:
            route_geometry = None

    return {
        "item_type": "transfer_trip",
        "transfer_trip_id": row["transfer_trip_id"],
        "submitted_at": row["submitted_at"],
        "status": row["status"],
        "submitted_by_email": row["submitted_by_email"],
        "start_stop_name": row["start_stop_name"],
        "end_stop_name": row["end_stop_name"],
        "start_stop": {
            "id": row["start_stop_id"],
            "name": row["start_stop_name"],
        },
        "end_stop": {
            "id": row["end_stop_id"],
            "name": row["end_stop_name"],
        },
        "planned_date": row["planned_date"],
        "planned_start_time": row["planned_start_time"],
        "planned_end_time": row["planned_end_time"],
        "tram_number": row["tram_number"],
        "reason": row["reason"],
        "notes": row["notes"],
        "route_distance_m": row["route_distance_m"],
        "route_geometry": route_geometry,
        "admin_note": row["admin_note"],
        "decision_message": row["decision_message"],
    }


@app.get("/api/my_transfer_trips")
def my_transfer_trips(request: Request) -> JSONResponse:
    user = _require_user(request)
    email = str(user.get("email") or "").strip().lower()

    if _use_postgres_read_backend():
        try:
            with PostgresAppQueries() as pg:
                rows = pg.list_transfer_trips_for_email(email, limit=1000)
        except Exception as exc:
            raise _postgres_read_unavailable(exc)
        return JSONResponse({"transfer_trips": rows})

    with get_db() as conn:
        rows = conn.execute(
            """
            SELECT * FROM transfer_trips
            WHERE lower(submitted_by_email) = ?
            ORDER BY submitted_at DESC
            """,
            (email,),
        ).fetchall()

    return JSONResponse({
        "transfer_trips": [_serialize_transfer_trip(r) for r in rows]
    })


@app.get("/api/admin/transfer_trips")
def admin_list_transfer_trips(
    request: Request,
    status: Optional[str] = None,
    email: Optional[str] = None,
) -> JSONResponse:
    _require_admin(request)

    if _use_postgres_read_backend():
        try:
            with PostgresAppQueries() as pg:
                rows = pg.list_transfer_trips(
                    status=status,
                    email=email,
                    limit=1000,
                )
        except Exception as exc:
            raise _postgres_read_unavailable(exc)
        return JSONResponse({"transfer_trips": rows})

    query = "SELECT * FROM transfer_trips WHERE 1=1"
    params: List[Any] = []

    if status:
        query += " AND status = ?"
        params.append(status.strip())
    if email:
        query += " AND lower(submitted_by_email) LIKE ?"
        params.append(f"%{email.strip().lower()}%")

    query += " ORDER BY submitted_at DESC"

    with get_db() as conn:
        rows = conn.execute(query, params).fetchall()

    return JSONResponse({
        "transfer_trips": [_serialize_transfer_trip(r) for r in rows]
    })


@app.get("/api/admin/transfer_trips/{trip_id}")
def admin_get_transfer_trip(trip_id: str, request: Request) -> JSONResponse:
    _require_admin(request)

    if _use_postgres_read_backend():
        try:
            with PostgresAppQueries() as pg:
                row = pg.get_transfer_trip_detail(trip_id)
        except Exception as exc:
            raise _postgres_read_unavailable(exc)
        if not row:
            raise HTTPException(status_code=404, detail="Transfer trip not found.")
        return JSONResponse(row)

    with get_db() as conn:
        row = conn.execute(
            "SELECT * FROM transfer_trips WHERE transfer_trip_id = ?",
            (trip_id,),
        ).fetchone()

    if not row:
        raise HTTPException(status_code=404, detail="Transfer trip not found.")

    return JSONResponse(_serialize_transfer_trip(row))


@app.post("/api/admin/transfer_trips/{trip_id}/status")
async def admin_update_transfer_trip_status(trip_id: str, request: Request) -> JSONResponse:
    user = _require_admin(request)
    body = await request.json()
    new_status = str(body.get("status") or "").strip().lower()
    admin_note = str(body.get("admin_note") or "").strip()
    decision_message = str(body.get("decision_message") or "").strip()

    allowed = {"submitted", "approved", "rejected"}
    if new_status not in allowed:
        raise HTTPException(status_code=400, detail="Invalid status.")

    if new_status == "submitted":
        decision_message = ""

    if _use_postgres_read_backend():
        try:
            with PostgresAppQueries() as pg:
                with pg._conn().transaction():
                    existing = pg.get_transfer_trip_detail(trip_id)
                    if not existing:
                        raise HTTPException(status_code=404, detail="Transfer trip not found.")
                    updated = pg.update_transfer_trip_status(
                        transfer_trip_id=trip_id,
                        status=new_status,
                        admin_note=admin_note,
                        decision_message=decision_message,
                    )
                    if updated:
                        write_audit_log(
                            actor_email=str(user.get("email") or "").strip().lower(),
                            actor_type="admin",
                            action_scope="admin_action",
                            action="transfer_trip_status_changed",
                            entity_type="transfer_trip",
                            entity_id=trip_id,
                            old_value={"status": existing.get("status")},
                            new_value={"status": new_status},
                            metadata={"transfer_trip_id": trip_id},
                            request=request,
                            conn=pg._conn(),
                        )
        except HTTPException:
            raise
        except Exception as exc:
            raise _postgres_read_unavailable(exc)
        if not updated:
            raise HTTPException(status_code=404, detail="Transfer trip not found.")
        return JSONResponse({
            "ok": True,
            "transfer_trip_id": trip_id,
            "status": new_status,
        })

    with get_db() as conn:
        row = conn.execute(
            "SELECT transfer_trip_id FROM transfer_trips WHERE transfer_trip_id = ?",
            (trip_id,),
        ).fetchone()

        if not row:
            raise HTTPException(status_code=404, detail="Transfer trip not found.")

        conn.execute(
            """
            UPDATE transfer_trips
            SET status = ?, admin_note = ?, decision_message = ?
            WHERE transfer_trip_id = ?
            """,
            (new_status, admin_note, decision_message, trip_id),
        )

    return JSONResponse({
        "ok": True,
        "transfer_trip_id": trip_id,
        "status": new_status,
    })


@app.delete("/api/admin/transfer_trips/{trip_id}")
async def admin_delete_transfer_trip(trip_id: str, request: Request) -> JSONResponse:
    user = _require_admin(request)

    if _use_postgres_read_backend():
        try:
            with PostgresAppQueries() as pg:
                with pg._conn().transaction():
                    existing = pg.get_transfer_trip_detail(trip_id)
                    if not existing:
                        raise HTTPException(status_code=404, detail="Transfer trip not found.")
                    deleted = pg.delete_transfer_trip(trip_id)
                    if deleted:
                        write_audit_log(
                            actor_email=str(user.get("email") or "").strip().lower(),
                            actor_type="admin",
                            action_scope="admin_action",
                            action="transfer_trip_deleted",
                            entity_type="transfer_trip",
                            entity_id=trip_id,
                            old_value={"status": existing.get("status")},
                            metadata={"deleted_entity_id": trip_id},
                            request=request,
                            conn=pg._conn(),
                        )
        except HTTPException:
            raise
        except Exception as exc:
            raise _postgres_read_unavailable(exc)
        if not deleted:
            raise HTTPException(status_code=404, detail="Transfer trip not found.")
        return JSONResponse({"ok": True, "deleted": trip_id})

    with get_db() as conn:
        row = conn.execute(
            "SELECT transfer_trip_id FROM transfer_trips WHERE transfer_trip_id = ?",
            (trip_id,),
        ).fetchone()

        if not row:
            raise HTTPException(status_code=404, detail="Transfer trip not found.")

        conn.execute(
            "DELETE FROM transfer_trips WHERE transfer_trip_id = ?",
            (trip_id,),
        )

    return JSONResponse({"ok": True, "deleted": trip_id})
