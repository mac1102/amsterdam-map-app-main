# PostgreSQL/PostGIS Migration Plan

This plan keeps the current app working while moving incrementally from SQLite and static GeoJSON toward PostgreSQL/PostGIS. AWS RDS, RDS Proxy, Multi-AZ, Redshift, managed cloud databases, asyncpg, pgRouting, and frontend rewrites are intentionally out of scope for the current migration.

## Deployment Assumption

- Development: PostgreSQL/PostGIS runs locally with Docker.
- Production prototype later: PostgreSQL/PostGIS may run locally on the same EC2 instance as the FastAPI app.
- Current app path remains SQLite-backed until each endpoint is migrated and verified.

## Phase 0 Inspection Report

Existing database files and functions:

- `backend/data/app.db`: main SQLite app database.
- `backend/wior.db`: WIOR cache database created by `backend/wior_fetch.py`.
- `backend/main.py`: defines `DB_PATH`, `get_db()`, `init_db()`, schema bootstrap, login, application, admin, transfer trip, health, map data, and `/api/click` routes.
- `backend/wior_fetch.py`: defines `get_wior_db()`, `init_wior_db()`, WIOR fetch/cache tables, tram proximity matching, and segment matching.
- Actual `backend/data/app.db` tables: `users`, `applications`, `application_targets`, `application_target_windows`, `application_people`, `application_uploads`, `transfer_trips`, `transfer_trip_points`, `tbgn_projects`.
- Current row counts inspected locally: `users` 2, `applications` 5, `application_targets` 5, `application_people` 5, `application_uploads` 5, `application_target_windows` 2, `transfer_trips` 2, `transfer_trip_points` 64, `tbgn_projects` 1.

Existing route files:

- `backend/main.py`: single main FastAPI route file for app pages, auth, map data, click, WIOR, applications, admin, segment bookings, transfers, and TBGN.
- `backend/tile_server.py`: raster tile serving helper.
- `backend/feature_index.py`: pixel-space feature hit-test helper used by `/api/click`.
- `backend/wior_fetch.py`: WIOR data sync/cache helper used by WIOR routes.

Existing GIS data files:

- `backend/data/features.json`: pixel-space map features for old `/api/click`; image size is 4972 by 7019.
- `static/data/spoor_data.js`: frontend rail GeoJSON source. Uses `properties.k` as the segment ID and `properties.li` as line ID.
- `backend/data/spoor_segments.geojson`: derived from `static/data/spoor_data.js`; uses `properties.segment_id`.
- `backend/data/tram_tracks.geojson`: line geometry exported from `static/data/spoor_data.js`.
- `static/data/haltes_data.js`: tram stop source, filtered/cleaned in `backend/main.py`.
- `static/data/spoortakken_data.js`: base network sections, currently visual-only.
- `static/data/bovenleiding_data.js` and `backend/data/Bovenleidingssecties v6.*`: overhead-line geometry.
- `backend/data/centerline.gpkg` and `backend/data/centerline_joined.gpkg`: source/derived GIS package files.
- `derived_rail_gap_segments.geojson` is not present in this checkout.

Current click-selection logic:

- Backend `/api/click` accepts pixel `x,y`, calls `feature_index.hit_test()`, and returns `hit`, `hit_type`, `feature`, `debug`, `map_px`, and `timestamp`.
- `FeatureIndex` loads `backend/data/features.json`, builds a simple grid index, checks stations first, then segments.
- Current frontend segment selection in `static/js/map.js` mostly bypasses `/api/click`: Leaflet layer click handlers select rail, switch, overhead, and stop features directly from static GeoJSON.
- Application custom-area pins store projected map pixel `x,y` values for the apply API.

Segment ID and coordinate findings:

- Frontend bookable rail segment IDs come from `static/data/spoor_data.js` property `k`.
- Derived backend segment GeoJSON stores the same value as `properties.segment_id`.
- `features.json` segment IDs are pixel-map IDs like `B:0:0:1`, not the same as KGE `properties.k` IDs.
- Static rail, tram track, stops, base network, and overhead data have coordinate ranges around longitude `4.77..5.01` and latitude `52.23..52.40`, so they are already EPSG:4326.
- WIOR code assumes WGS84 input and transforms to EPSG:28992 only for metric Shapely operations.

Risks before migration:

- There are two selection models: pixel hit-test data in `features.json` and Leaflet/static GeoJSON selection using KGE IDs. PostGIS `/api/click` should target longitude/latitude/KGE IDs, but old `/api/click` accepts pixels and returns old IDs.
- `application_targets.segment_id` currently references KGE IDs from `properties.k`, while `features.json` IDs are incompatible.
- WIOR conflicts currently loop in Python over cached SQLite rows and segment ID lists.
- `derived_rail_gap_segments.geojson` is expected by the migration plan but absent from this repo.
- `backend/main.py` is large and owns many unrelated concerns, so endpoint-by-endpoint migration needs tight scope.

## Phase 1 Local PostGIS Setup

Added local Docker PostGIS with database `gvb_map`, user `gvb_user`, and local development password `change_me`.

Start local PostGIS:

```powershell
docker compose up -d postgis
```

Use this local development URL:

```text
DATABASE_URL=postgresql://gvb_user:change_me@localhost:5432/gvb_map
```

The FastAPI `/health` endpoint now reports SQLite status and optional PostgreSQL status. PostgreSQL being unset reports `not_configured` and does not break the SQLite app path.

## Phase 2 Schema Baseline

The initial PostgreSQL/PostGIS schema is in `database/schema_postgres.sql`.

Included current SQLite tables:

- `users`
- `applications`
- `application_targets`
- `application_target_windows`
- `application_people`
- `application_uploads`
- `transfer_trips`
- `transfer_trip_points`
- `tbgn_projects`

Included new PostgreSQL/PostGIS tables:

- `tram_lines`
- `tram_segments`
- `tram_stops`
- `wior_work_areas`
- `audit_logs`

The schema uses SRID 4326 and keeps KGE/static GeoJSON IDs as canonical segment references. It does not use `features.json` pixel IDs. `application_targets.segment_id` references `tram_segments.segment_id`. The `applications.project_start` and `applications.project_end` columns are nullable summary columns added for dashboard/date indexing; the per-target windows remain on `application_targets` and `application_target_windows`.

Initialize without dropping existing tables:

```powershell
$env:DATABASE_URL="postgresql://gvb_user:change_me@localhost:5432/gvb_map"
py -3 scripts/init_postgis_schema.py
```

Only for local reset testing:

```powershell
py -3 scripts/init_postgis_schema.py --reset
```

## Phase 3 Indexes

The schema includes required spatial indexes:

- `tram_segments_geom_idx`
- `tram_stops_geom_idx`
- `wior_work_areas_geom_idx`

The schema includes required normal indexes:

- `applications_status_idx`
- `applications_dates_idx`
- `application_targets_segment_idx`
- `application_targets_application_idx`
- `audit_logs_created_at_idx`

## Phase 4 Static GIS Import

Implemented static GIS import scripts:

- `scripts/import_static_gis_to_postgis.py`: idempotent UPSERT import for `tram_lines`, `tram_segments`, and `tram_stops`.
- `scripts/check_postgis_data.py`: read-only verification helper for PostGIS version, row counts, geometry validity, and WGS84 extents.

Run the import locally:

```powershell
$env:DATABASE_URL="postgresql://gvb_user:change_me@localhost:5432/gvb_map"
py -3 scripts/import_static_gis_to_postgis.py
py -3 scripts/import_static_gis_to_postgis.py
py -3 scripts/check_postgis_data.py
py -3 -m py_compile scripts/import_static_gis_to_postgis.py scripts/check_postgis_data.py
```

Source file behavior:

- `backend/data/spoor_segments.geojson` is preferred only when its `properties.segment_id` set fully matches `static/data/spoor_data.js` `properties.k`.
- In this checkout, `backend/data/spoor_segments.geojson` has fewer segment IDs than `static/data/spoor_data.js`, so the importer falls back to `static/data/spoor_data.js` to keep the KGE/static segment ID set complete.
- The fallback source contains 116 degenerate one-point line features and one feature without `properties.k`; these are skipped. The resulting valid `tram_segments` count is 4,758.
- `static/data/spoor_data.js` is a JavaScript assignment, not pure JSON; the importer extracts the assigned GeoJSON object without executing JavaScript.
- `static/data/haltes_data.js` is also JavaScript; the importer extracts `RAW_TRAMMETRO_PUNTEN_2026` and applies the same tram-stop filter used by the frontend data wrapper.
- `derived_rail_gap_segments.geojson` is optional. It is checked in the repo root, `backend/data`, and `static/data`. It is missing in this checkout, so the import prints `derived rail gap file not found; skipping.` and continues.
- `features.json` pixel IDs are intentionally not used as canonical segment IDs.

Validation behavior:

- Input geometries are treated as EPSG:4326 only after coordinate-range checks.
- Coordinates outside WGS84 bounds fail the import because they likely indicate projected coordinates such as EPSG:28992.
- Segment geometries are inserted as `geometry(MultiLineString, 4326)` using `ST_Multi`.
- Stop geometries are inserted as `geometry(Point, 4326)`.
- Re-running the import uses UPSERT and should not duplicate rows.
- SQLite remains untouched and the frontend behavior is unchanged.

### Stop Filter Correction

The current static/frontend stop filter in `static/data/haltes_data.js` now treats line `29` as a valid tram display code.

Correct tram display codes:

```text
01, 02, 04, 05, 06, 07, 12, 13, 14, 17, 19, 24, 25, 26, 27, 29
```

Metro-related codes `50`, `51`, `52`, `53`, and `54` remain excluded from tram-line logic. The static path still filters to `properties.Modaliteit === "Tram"`, cleans `Lijn_select` to the allowed tram codes, and hides records whose cleaned `Lijn_select` is empty.

`scripts/check_stop_filters.py` reports the source-file effect:

- Raw `Modaliteit = Tram` records: 197
- Old frontend-visible count using codes through `27`: 184
- Corrected frontend-visible count including `29`: 184
- Records added by line `29` in this checkout: 0

The code now accepts line `29`, but this source checkout does not currently contain `Modaliteit = Tram` records with `Lijn_select = 29`, so the visible stop count does not increase locally.

PostGIS `tram_stops` now preserves raw tram-classified stop metadata:

- `raw_modaliteit`
- `raw_lijn`
- `raw_lijn_select`
- `current_display_lijn`
- `current_display_lijn_select`
- `valid_tram_lijn`
- `valid_tram_lijn_select`
- `is_current_frontend_visible`
- `is_valid_tram_line_stop`
- `updated_at`

The importer stores every source feature where `Modaliteit == "Tram"` and does not import `Modaliteit == "Metro"` records into `tram_stops`. Current local PostGIS stop metadata:

- Total raw tram source records stored: 197
- `is_current_frontend_visible = true`: 184
- `is_valid_tram_line_stop = true`: 184
- Hidden records: 12 with `Lijn_select = -`, 1 with `Lijn_select = 50|51`
- The `50|51` record is stored as a raw tram-classified source record but is not counted as a valid tram-line stop.

## Phase 5 PostGIS Nearest Segment Helper

Implemented Phase 5 without replacing `/api/click`:

- `backend/postgis_queries.py` defines `find_nearest_segment_postgis(lng, lat, radius_m=30.0)`.
- `scripts/test_postgis_click.py` exercises the helper from the command line.
- The helper reads `DATABASE_URL`, uses synchronous psycopg3, validates WGS84 longitude/latitude, returns `None` if PostgreSQL/PostGIS is unavailable, and queries `tram_segments` with `ST_DWithin` before ordering candidates by `ST_Distance`.
- The result contains `segment_id`, `line_id`, `line_name`, `source`, `bookable`, `distance_m`, and GeoJSON geometry.
- This Phase 5 helper uses longitude/latitude PostGIS selection, not the old pixel `x/y` hit-test.
- `/api/click` has not been switched yet; `backend/feature_index.py` remains untouched.

Phase 5 local test commands:

```powershell
$env:DATABASE_URL="postgresql://gvb_user:change_me@localhost:5432/gvb_map"
py -3 scripts/test_postgis_click.py --lng 4.898486 --lat 52.378897 --radius-m 30
py -3 scripts/test_postgis_click.py --lng 4.884466 --lat 52.365024 --radius-m 30
py -3 scripts/test_postgis_click.py --lng 4.8820313 --lat 52.3637101 --radius-m 30
py -3 scripts/test_postgis_click.py --lng 5.5 --lat 53.0 --radius-m 30
```

Observed local results:

- `4.898486, 52.378897`: found `K0010-00150`
- `4.884466, 52.365024`: found `L0120-11730`
- `4.8820313, 52.3637101`: found `K0120-11910`
- `5.5, 53.0`: no segment found

## Phase 6 Dual-Mode `/api/click`

Implemented temporary dual-mode click handling:

- Payloads with pixel `x/y` continue to use the old `backend/feature_index.py` hit-test path.
- Payloads with geographic `lng/lat` use `find_nearest_segment_postgis(lng, lat, radius_m)`.
- Payloads with both coordinate systems try PostGIS first, then fall back to the old pixel path when PostGIS returns no result or is unavailable.
- Invalid coordinate payloads return a controlled `400` instead of crashing.
- `/api/click` is not fully cut over yet; this phase is for stabilizing the PostGIS path beside the old behavior.

Important ID boundary:

- Old pixel mode still returns `features.json` IDs such as `B:0:0:1`.
- New PostGIS mode returns KGE/static IDs from `tram_segments.segment_id`, such as `K0010-00150`.
- These ID systems must not be mixed. `application_targets.segment_id` should align with KGE/static IDs.

PostGIS mode response shape keeps the existing top-level keys:

- `hit`
- `hit_type`
- `feature`
- `debug`
- `map_px`
- `timestamp`

For PostGIS hits, `feature` includes `id`, `segment_id`, `line_id`, `line_name`, `source`, `bookable`, `distance_m`, and GeoJSON `geometry`. `debug.mode` is `postgis_lnglat`. `map_px` is `null`.

Manual PowerShell checks:

```powershell
$body = @{
  lng = 4.898486
  lat = 52.378897
  radius_m = 30
} | ConvertTo-Json

Invoke-RestMethod -Method Post -Uri "http://127.0.0.1:8000/api/click" -ContentType "application/json" -Body $body
```

Expected: `hit = true`, `hit_type = segment`, `debug.mode = postgis_lnglat`, and a KGE/static `feature.segment_id`.

```powershell
$body = @{
  lng = 5.5
  lat = 53.0
  radius_m = 30
} | ConvertTo-Json

Invoke-RestMethod -Method Post -Uri "http://127.0.0.1:8000/api/click" -ContentType "application/json" -Body $body
```

Expected: `hit = false`, no crash.

Automated local helper:

```powershell
$env:DATABASE_URL="postgresql://gvb_user:change_me@localhost:5432/gvb_map"
py -3 scripts/test_api_click_modes.py
```

The helper tests old pixel mode, lng/lat PostGIS mode, combined PostGIS-first mode, simulated old-pixel fallback, invalid coordinates, and outside-Amsterdam no-hit.

## Phase 7A Dry-Run Relational Migration

Implemented safe SQLite-to-PostgreSQL relational copy scripts:

- `scripts/migrate_sqlite_to_postgres.py`
- `scripts/check_relational_migration.py`

This phase only copies relational data into PostgreSQL for verification. The app runtime still uses SQLite through `backend/data/app.db`; no login, submission, admin, upload, or `/api/click` runtime path has been switched to PostgreSQL.

Migrated tables:

- `users`
- `applications`
- `application_targets`
- `application_target_windows`
- `application_people`
- `application_uploads`
- `transfer_trips`
- `transfer_trip_points`
- `tbgn_projects`

Migration safeguards:

- Dry-run is the default.
- `--apply` is required before any PostgreSQL writes.
- `--apply` creates a timestamped SQLite backup first:
  `backups/app_YYYYMMDD_HHMMSS_before_postgres_migration.db`
- `--reset-relational` is optional and explicit.
- Spatial tables are not dropped or deleted: `tram_lines`, `tram_segments`, `tram_stops`, and `wior_work_areas` are not reset by this script.
- The script uses synchronous psycopg3 and transactions.
- Existing IDs and password hashes are preserved where PostgreSQL constraints allow.

Segment ID note:

- Existing SQLite `application_targets.segment_id` can contain old pixel IDs from `features.json`, for example `H:118:0:14`.
- PostgreSQL `application_targets.segment_id` references `tram_segments.segment_id`, which uses KGE/static IDs.
- During relational copy, source segment IDs that do not exist in `tram_segments` are migrated as `NULL` in `application_targets.segment_id` so PostgreSQL foreign keys remain valid. Existing metadata such as `asset_id` still carries the original source value where it existed.
- `scripts/check_relational_migration.py` reports source missing segment IDs and PostgreSQL match counts.

Observed local validation after `--apply`:

- Backup created: `backups/app_20260516_203110_before_postgres_migration.db`
- Row counts matched for all migrated relational tables.
- Primary keys matched for all migrated relational tables.
- Password hash mismatches: 0
- Join checks missing references: 0
- SQLite source `application_targets.segment_id` non-null rows: 5
- SQLite source rows matching `tram_segments`: 3
- SQLite source missing KGE/static segment sample: `H:118:0:14`
- PostgreSQL `application_targets.segment_id` non-null rows: 3
- PostgreSQL `application_targets` missing `tram_segments`: 0

Commands:

```powershell
$env:DATABASE_URL="postgresql://gvb_user:change_me@localhost:5432/gvb_map"

# Dry run; no PostgreSQL writes.
py -3 scripts/migrate_sqlite_to_postgres.py

# Apply without deleting existing relational rows.
py -3 scripts/migrate_sqlite_to_postgres.py --apply

# Optional local mirror reset, never touching spatial tables.
py -3 scripts/migrate_sqlite_to_postgres.py --apply --reset-relational

# Verify row counts, joins, password hashes, primary keys, and segment references.
py -3 scripts/check_relational_migration.py

py -3 -m py_compile scripts/migrate_sqlite_to_postgres.py scripts/check_relational_migration.py
py -3 -c "import backend.main as m; print(m.health_check())"
```

## Phase 8A PostgreSQL Read Helpers

Implemented PostgreSQL relational read helpers beside the existing SQLite runtime:

- `backend/postgres_app_queries.py`
- `scripts/compare_sqlite_postgres_reads.py`

This phase adds read-only PostgreSQL access for comparison and future endpoint migration. The live application runtime still defaults to SQLite. No routes were switched to PostgreSQL in this phase.

Read helper coverage:

- `get_user_by_email_pg(email)`
- `list_applications_pg(status=None, limit=100)`
- `list_pending_applications_pg(limit=100)`
- `get_application_detail_pg(application_id)`
- `get_application_targets_pg(application_id)`
- `get_application_people_pg(application_id)`
- `get_application_uploads_pg(application_id)`
- `list_transfer_trips_pg(limit=100)`
- `get_transfer_trip_points_pg(trip_id)`
- `list_tbgn_projects_pg(limit=100)`

The helper module uses synchronous psycopg3, reads `DATABASE_URL`, and returns dictionaries/lists shaped to match existing backend read serializers. `PostgresAppQueries` can be used as a context manager so comparison scripts can reuse one connection across many reads.

Comparison behavior:

- Compares users count and user lookup by email.
- Compares application counts, pending application counts, application list IDs, full application detail, targets, people, and uploads.
- Compares transfer trip counts, IDs, detail, and transfer trip points.
- Compares TBGN project counts, IDs, and details.
- Allows only the documented Phase 7A `segment_id` normalization: old pixel IDs that do not exist in `tram_segments` may be `NULL` in PostgreSQL `application_targets.segment_id`.

Observed local comparison:

- Failures: 0
- Expected warnings: 2
- Warning sample: SQLite old pixel/KGE-missing `segment_id` `H:118:0:14` normalized to PostgreSQL `NULL`

Commands:

```powershell
$env:DATABASE_URL="postgresql://gvb_user:change_me@localhost:5432/gvb_map"

py -3 scripts/check_relational_migration.py
py -3 scripts/compare_sqlite_postgres_reads.py

py -3 -m py_compile backend/main.py backend/postgis_queries.py backend/postgres_app_queries.py scripts/compare_sqlite_postgres_reads.py scripts/check_relational_migration.py

py -3 -c "import backend.main as m; print(m.health_check())"
py -3 scripts/test_api_click_modes.py
```

Runtime status after Phase 8A:

- Login still uses SQLite.
- Application submission still uses SQLite.
- Admin approve/decline still uses SQLite.
- Upload metadata writes still use SQLite.
- `/api/click` remains dual-mode from Phase 6.
- `backend/feature_index.py` remains untouched.
- No asyncpg or pgRouting has been added.

## Phase 8B Feature-Flagged Read Routes

Implemented feature-flagged PostgreSQL read routing for selected read-only endpoints.

Default behavior remains SQLite:

```text
APP_DB_BACKEND=sqlite
```

Set this only for controlled local testing of read routes:

```text
APP_DB_BACKEND=postgres
```

Feature-flagged read routes:

- `GET /api/my_applications`
- `GET /api/admin/applications`
- `GET /api/admin/applications/{application_id}`
- `GET /api/tbgn/projects`
- `GET /api/admin/tbgn`
- `GET /api/admin/tbgn/{project_id}`
- `GET /api/my_transfer_trips`
- `GET /api/admin/transfer_trips`
- `GET /api/admin/transfer_trips/{trip_id}`

Runtime rules:

- Any `APP_DB_BACKEND` value other than `postgres` uses SQLite.
- If `APP_DB_BACKEND=postgres`, these selected read routes use `PostgresAppQueries`.
- If PostgreSQL is explicitly selected but unavailable, selected read routes return `503` instead of silently falling back.
- Write endpoints still use SQLite.
- Login still uses SQLite.
- Application submission still uses SQLite.
- Admin approve/decline still uses SQLite.
- Upload metadata writes still use SQLite.
- `/api/click` remains the Phase 6 dual-mode implementation.

Route comparison helper:

- `scripts/test_read_route_backend_modes.py`

The script invokes the selected read route functions once with `APP_DB_BACKEND=sqlite` and once with `APP_DB_BACKEND=postgres`, then compares normalized JSON response shapes and values. It allows only the documented Phase 7A segment-ID normalization, where old pixel/KGE-missing values such as `H:118:0:14` are `NULL` in PostgreSQL `application_targets.segment_id`.

Observed local route comparison:

- Failures: 0
- Expected warnings: 6 route-level sightings of the known `H:118:0:14` normalization

Commands:

```powershell
$env:DATABASE_URL="postgresql://gvb_user:change_me@localhost:5432/gvb_map"

py -3 scripts/check_relational_migration.py
py -3 scripts/compare_sqlite_postgres_reads.py
py -3 scripts/test_read_route_backend_modes.py

py -3 -m py_compile backend/main.py backend/postgis_queries.py backend/postgres_app_queries.py scripts/compare_sqlite_postgres_reads.py scripts/check_relational_migration.py scripts/test_read_route_backend_modes.py

py -3 -c "import backend.main as m; print(m.health_check())"
py -3 scripts/test_api_click_modes.py
```

## Phase 8C Controlled Read-Route Runtime Testing

Implemented controlled runtime checks for the feature-flagged PostgreSQL read routes.

Backend diagnostics:

- `/health` still keeps the existing `database` and `postgres` fields.
- `/health` now also reports `sqlite.status`, `app_db_backend.raw`, `app_db_backend.resolved`, `app_db_backend.selected_read_routes_backend`, and PostgreSQL configured/available flags.
- Any unknown `APP_DB_BACKEND` value still resolves to `sqlite`.
- Default behavior remains `APP_DB_BACKEND=sqlite`.

Added HTTP-level route comparison:

- `scripts/test_read_routes_http_modes.py`

The script uses FastAPI `TestClient` when `httpx` is installed, patches route auth in-process, calls selected read routes once with `APP_DB_BACKEND=sqlite` and once with `APP_DB_BACKEND=postgres`, and compares normalized HTTP status codes plus JSON bodies. `requirements.txt` now includes `httpx` for this test path. In an environment where `httpx` has not been installed yet, the script falls back to a small GET-only ASGI client so the route layer can still be checked. The only allowed warning is the known Phase 7A normalization where old pixel/KGE-missing segment IDs such as `H:118:0:14` may be `NULL` in PostgreSQL `application_targets.segment_id`.

Added PostgreSQL read mirror staleness check:

- `scripts/check_postgres_read_staleness.py`

The script compares SQLite and PostgreSQL for:

- latest `applications.submitted_at`
- `applications` count
- `application_targets` count
- `application_uploads` count

If SQLite has newer or more rows, it prints:

```text
PostgreSQL read mirror is stale. Run migrate_sqlite_to_postgres.py --apply --reset-relational before testing APP_DB_BACKEND=postgres.
```

Important current runtime warning:

- `APP_DB_BACKEND=postgres` only switches selected read routes.
- It does not switch login.
- It does not switch application submission.
- It does not switch admin approve/decline.
- It does not switch upload writes.
- It does not switch WIOR refresh.
- Writes still go to SQLite, so PostgreSQL read data can become stale unless `scripts/migrate_sqlite_to_postgres.py --apply --reset-relational` is re-run before testing PostgreSQL read mode.

Manual browser checklist with SQLite default:

```powershell
$env:APP_DB_BACKEND="sqlite"
```

Test:

- login
- my applications
- admin applications
- admin application detail
- TBGN list/detail
- transfer trips list/detail
- `/api/click` old `x/y` mode
- `/api/click` new `lng/lat` mode
- WIOR status endpoint

Manual browser checklist with PostgreSQL read mode:

```powershell
$env:APP_DB_BACKEND="postgres"
```

Test read-only pages only:

- my applications
- admin applications
- admin application detail
- TBGN list/detail
- transfer trips list/detail

Do not treat write testing under `APP_DB_BACKEND=postgres` as migrated yet. Login and write routes still use SQLite in this phase.

Commands:

```powershell
$env:DATABASE_URL="postgresql://gvb_user:change_me@localhost:5432/gvb_map"

py -3 scripts/check_relational_migration.py
py -3 scripts/compare_sqlite_postgres_reads.py
py -3 scripts/test_read_route_backend_modes.py
py -3 scripts/test_read_routes_http_modes.py
py -3 scripts/check_postgres_read_staleness.py

py -3 -m py_compile backend/main.py backend/postgres_app_queries.py backend/postgis_queries.py scripts/compare_sqlite_postgres_reads.py scripts/check_relational_migration.py scripts/test_read_route_backend_modes.py scripts/test_read_routes_http_modes.py scripts/check_postgres_read_staleness.py scripts/test_api_click_modes.py

py -3 -c "import backend.main as m; print(m.health_check())"
py -3 scripts/test_api_click_modes.py
```

## Phase 8D Feature-Flagged PostgreSQL Runtime Writes

Implemented PostgreSQL application-runtime writes behind `APP_DB_BACKEND=postgres`.

Default behavior remains SQLite:

```text
APP_DB_BACKEND=sqlite
```

When `APP_DB_BACKEND=postgres`, the following runtime flows use PostgreSQL:

- login/user lookup
- application submission
- application target insertion
- application target window insertion
- application people insertion
- application upload metadata insertion
- application status/admin note/decision message update
- application delete
- transfer trip submission
- transfer trip point insertion
- transfer trip status/admin note/decision message update
- transfer trip delete
- TBGN project create/update/delete
- `GET /api/line_status`
- `GET /api/segment_bookings`

SQLite/default behavior remains unchanged for the same routes when `APP_DB_BACKEND` is unset or set to `sqlite`.

Write routes inspected before Phase 8D:

- `POST /api/login`: handled in Phase 8D.
- `POST /api/apply`: handled in Phase 8D.
- `POST /api/admin/applications/{application_id}/status`: handled in Phase 8D.
- `DELETE /api/admin/applications/{application_id}`: handled in Phase 8D.
- `POST /api/transfer/apply`: handled in Phase 8D.
- `POST /api/admin/transfer_trips/{trip_id}/status`: handled in Phase 8D.
- `DELETE /api/admin/transfer_trips/{trip_id}`: handled in Phase 8D.
- `POST /api/admin/tbgn`: handled in Phase 8D.
- `PUT /api/admin/tbgn/{project_id}`: handled in Phase 8D.
- `DELETE /api/admin/tbgn/{project_id}`: handled in Phase 8D.
- Startup admin/seed user bootstrap writes: intentionally deferred; they remain SQLite bootstrap behavior for now.
- WIOR refresh/cache writes: intentionally deferred.
- WIOR conflict detection: intentionally deferred to Phase 9.

PostgreSQL write behavior:

- Multi-table application submission is transactional in PostgreSQL.
- Application submission inserts `applications`, `application_targets`, `application_target_windows`, `application_people`, and `application_uploads` together.
- Transfer submission inserts `transfer_trips` and `transfer_trip_points` together.
- Upload files still live on disk in `backend/data/uploads`; PostgreSQL stores metadata only.
- If PostgreSQL mode is selected and a required PostgreSQL operation fails, the route returns a controlled PostgreSQL-unavailable error instead of silently writing to SQLite.

Segment ID handling:

- `application_targets.segment_id` stores only valid KGE/static IDs that exist in `tram_segments.segment_id`.
- Old `features.json` pixel IDs or custom-area IDs do not violate the PostgreSQL FK.
- In PostgreSQL mode, those non-KGE values are stored as `NULL` in `application_targets.segment_id` while the original value remains in `asset_id` when provided.
- The old pixel ID system and KGE/static segment ID system remain intentionally separate.

Pre-test sync requirement:

```powershell
$env:DATABASE_URL="postgresql://gvb_user:change_me@localhost:5432/gvb_map"

py -3 scripts/migrate_sqlite_to_postgres.py --apply --reset-relational
py -3 scripts/check_relational_migration.py
py -3 scripts/check_postgres_read_staleness.py
```

This makes PostgreSQL start from the latest SQLite relational data before testing `APP_DB_BACKEND=postgres` writes.

Write-mode test helper:

- `scripts/test_postgres_write_mode.py`

The helper sets `APP_DB_BACKEND=postgres`, creates a temporary PostgreSQL-only test user, exercises login, creates a temporary application with upload metadata, verifies PostgreSQL read-after-write, updates application status, exercises TBGN create/update/delete, exercises transfer create/status/delete when routeable stops are available, deletes temporary rows, and removes the temporary uploaded test file.

Commands:

```powershell
$env:DATABASE_URL="postgresql://gvb_user:change_me@localhost:5432/gvb_map"

py -3 scripts/migrate_sqlite_to_postgres.py --apply --reset-relational
py -3 scripts/check_relational_migration.py
py -3 scripts/check_postgres_read_staleness.py

py -3 scripts/compare_sqlite_postgres_reads.py
py -3 scripts/test_read_route_backend_modes.py
py -3 scripts/test_read_routes_http_modes.py
py -3 scripts/test_postgres_write_mode.py
py -3 scripts/test_api_click_modes.py

py -3 -m py_compile backend/main.py backend/postgres_app_queries.py backend/postgis_queries.py scripts/test_postgres_write_mode.py scripts/check_postgres_read_staleness.py scripts/test_api_click_modes.py

$env:APP_DB_BACKEND="sqlite"
py -3 -c "import backend.main as m; print(m.health_check())"

$env:APP_DB_BACKEND="postgres"
py -3 -c "import backend.main as m; print(m.health_check())"
```

Rollback for local testing:

- Set `APP_DB_BACKEND=sqlite` and restart the app.
- PostgreSQL-only test or runtime data will not automatically appear in SQLite.
- Before a future production cutover, run a final SQLite-to-PostgreSQL migration and verify counts before setting `APP_DB_BACKEND=postgres`.

Still unchanged in Phase 8D:

- SQLite remains the default runtime.
- WIOR refresh/cache still uses the existing WIOR path.
- WIOR conflict detection has not moved to spatial SQL.
- `/api/click` remains dual-mode.
- `backend/feature_index.py` remains untouched.
- No asyncpg or pgRouting has been added.

## Phase 9A PostGIS WIOR Mirror And Conflict Helper

Implemented a PostGIS-backed WIOR mirror and comparison path beside the existing WIOR system. The default WIOR API behavior remains legacy.

Current WIOR system inspection:

- `backend/wior_fetch.py` owns the current WIOR cache and refresh logic.
- `backend/wior_refresh_job.py` remains the one-shot refresh entrypoint used by the external refresh service/timer design.
- `backend/wior.db` remains the SQLite WIOR cache.
- Current WIOR endpoints remain in `backend/main.py`.

SQLite WIOR cache tables:

- `wior_sync_runs`: refresh run metadata, status, fetched/loaded counts, and error message.
- `wior_features`: raw-ish WIOR API records keyed by `wior_id`.
- `wior_features_serving`: production-facing filtered WIOR rows near the tram corridor, keyed by `wior_id`.

Important WIOR fields:

- IDs/reference: `wior_id`, `project_code`
- Title/text: `project_name`, `description`
- State/type: `status`, `work_type`
- Dates: `start_date`, `end_date`
- Geometry: `geometry_type`, `geometry_json`
- Serving flags: `is_active`, `is_upcoming_7d`, `is_upcoming_30d`, `is_expired`, `is_near_tram`
- Matched tram segments: `segment_ids_json`

Current legacy behavior:

- WIOR refresh fetches Amsterdam WIOR GeoJSON, stores rows in `wior_features`, deletes expired source rows, and rebuilds `wior_features_serving`.
- Serving rows are built by transforming WIOR geometries and tram tracks to EPSG:28992, buffering the tram corridor by 10 meters, and keeping only WIOR geometries intersecting that corridor.
- Segment matching uses `backend/data/spoor_segments.geojson`, transforms to EPSG:28992, buffers segments by 2 meters, and stores matched KGE/static IDs in `segment_ids_json`.
- `GET /api/wior/features` reads `wior_features_serving`.
- `GET /api/wior/status` checks whether serving rows exist.
- `POST /api/wior/conflicts/check` defaults to the legacy path: it checks whether requested `segment_id` exists in `segment_ids_json` and whether requested dates overlap WIOR dates.

PostGIS WIOR schema additions:

- `wior_work_areas.wior_id`
- `wior_work_areas.title`
- `wior_work_areas.status`
- `wior_work_areas.start_date`
- `wior_work_areas.end_date`
- `wior_work_areas.raw_payload`
- `wior_work_areas.segment_ids`
- `wior_work_areas.is_active`
- `wior_work_areas.is_upcoming_7d`
- `wior_work_areas.is_upcoming_30d`
- `wior_work_areas.is_expired`
- `wior_work_areas.is_near_tram`
- `wior_work_areas.last_built_at`
- `wior_work_areas.updated_at`

Added WIOR indexes:

- `wior_work_areas_wior_id_uidx`
- `wior_work_areas_dates_idx`
- `wior_work_areas_status_idx`

WIOR-to-PostGIS sync:

- `scripts/sync_wior_to_postgis.py`

The script reads `backend/wior.db`, mirrors `wior_features_serving` into `wior_work_areas`, stores geometry in SRID 4326, preserves source payload as JSONB when available, stores matched segment IDs as JSONB, and uses UPSERT on `wior_id`.

Safety behavior:

- Dry-run is the default.
- `--apply` is required before writing.
- `--reset-wior-postgis` is explicit and only available with `--apply`.
- The script does not modify `backend/wior.db`.
- The script does not modify `backend/data/app.db`.
- The script does not modify `tram_segments`, `tram_stops`, or `tram_lines`.

PostGIS WIOR helper:

- `backend/postgis_wior_queries.py`

Implemented helpers:

- `is_postgis_wior_available()`
- `find_wior_near_segments_postgis(segment_ids, start_date, end_date, buffer_m=10)`
- `find_wior_near_geometry_postgis(geojson, start_date, end_date, buffer_m=10)`
- `find_wior_conflicts_postgis(targets, buffer_m=10)`

The segment conflict helper uses `tram_segments.geom`, `wior_work_areas.geom`, date overlap logic, and `ST_DWithin(...::geography, ...::geography, buffer_m)`.

Conflict endpoint mode:

- Default / auto mode uses PostGIS first, then legacy fallback:
  `POST /api/wior/conflicts/check`
- Explicit legacy mode forces the old SQLite/cache logic:
  `POST /api/wior/conflicts/check?backend=legacy`
- Explicit PostGIS mode:
  `POST /api/wior/conflicts/check?backend=postgis`
- Compare mode:
  `POST /api/wior/conflicts/check?backend=compare`

Default mode is also available as:
`POST /api/wior/conflicts/check?backend=auto`

Default / auto behavior:

- Checks that `DATABASE_URL` is set, PostgreSQL is reachable, `tram_segments` and `wior_work_areas` exist, and the `wior_work_areas` mirror has rows from `wior_sqlite_serving`.
- Runs PostGIS WIOR conflict detection when those checks pass.
- Falls back to the legacy WIOR conflict logic when PostGIS is unavailable, the mirror is empty, or the PostGIS helper errors.
- Preserves the frontend-required top-level response fields: `ok`, `has_conflicts`, `conflict_count`, and `conflicts`.
- Adds safe debug metadata such as `backend`, `fallback_used`, `fallback_reason`, and `postgis_mirror`.

Explicit `backend=postgis` does not silently fall back to legacy; if the PostGIS mirror is unavailable it returns the controlled route error.

`backend=compare` runs both paths and returns both results plus difference/debug information.

Comparison helper:

- `scripts/compare_wior_conflicts.py`

It compares legacy WIOR conflict logic vs the new PostGIS helper for:

- a known real segment/date sample from `wior_features_serving`
- a same-segment far-future no-conflict sample
- a non-existent/outside segment ID sample

Observed local WIOR mirror and comparison:

- Source serving rows: 21
- Rows upserted into `wior_work_areas`: 21
- Invalid WIOR geometries: 0
- Empty WIOR geometries: 0
- WIOR extent: roughly Amsterdam longitude/latitude
- Known sample old conflict count: 1
- Known sample PostGIS conflict count: 1
- Matching references: 1
- No-conflict and outside segment samples: 0 in both paths

Commands:

```powershell
$env:DATABASE_URL="postgresql://gvb_user:change_me@localhost:5432/gvb_map"

# Existing WIOR refresh path remains available.
py -3 -m backend.wior_refresh_job

# Dry run, then apply PostGIS WIOR mirror.
py -3 scripts/sync_wior_to_postgis.py
py -3 scripts/sync_wior_to_postgis.py --apply

# Optional explicit local reset of only WIOR mirror rows.
py -3 scripts/sync_wior_to_postgis.py --apply --reset-wior-postgis

py -3 scripts/check_postgis_data.py
py -3 scripts/compare_wior_conflicts.py

py -3 scripts/test_wior_conflict_modes.py
py -3 scripts/test_api_click_modes.py
py -3 scripts/test_postgres_write_mode.py

py -3 -m py_compile backend/main.py backend/postgres_app_queries.py backend/postgis_queries.py backend/postgis_wior_queries.py scripts/sync_wior_to_postgis.py scripts/compare_wior_conflicts.py scripts/test_wior_conflict_modes.py

$env:APP_DB_BACKEND="postgres"
py -3 -c "import backend.main as m; print(m.health_check())"
```

After every WIOR refresh, sync the PostGIS mirror before treating PostGIS conflict results as current:

```powershell
py -3 -m backend.wior_refresh_job
py -3 scripts/sync_wior_to_postgis.py --apply
```

Future EC2/systemd note: later, `wior-refresh.service` can be updated to run both commands in that order:

1. `python -m backend.wior_refresh_job`
2. `python scripts/sync_wior_to_postgis.py --apply`

No systemd files are changed in Phase 9B.

Still unchanged after Phase 9B:

- `backend/wior.db` remains the current WIOR refresh cache.
- The systemd refresh design remains external to FastAPI startup.
- Old Python WIOR conflict logic remains available.
- WIOR refresh is not moved into PostGIS yet.
- `/api/click` remains dual-mode.
- `feature_index.py` remains untouched.
- No asyncpg or pgRouting has been added.

Phase 9B changes the default WIOR conflict path to PostGIS-first with legacy fallback. It does not delete `backend/wior.db`, remove legacy WIOR logic, or change the WIOR refresh/systemd design.

## Phase 9C Combined WIOR Refresh And PostGIS Sync Job

Added a single background job entrypoint:

- `backend/wior_refresh_and_sync_job.py`

Run locally:

```powershell
$env:DATABASE_URL="postgresql://gvb_user:change_me@localhost:5432/gvb_map"
py -3 -m backend.wior_refresh_and_sync_job
```

The combined job:

- Runs the existing WIOR refresh into `backend/wior.db` first.
- Runs the PostGIS WIOR mirror sync after a successful refresh.
- Uses the same sync behavior as:
  `py -3 scripts/sync_wior_to_postgis.py --apply`
- Prints the WIOR refresh result, PostGIS sync summary, and combined success status.
- Exits `0` on success.
- Exits non-zero if the refresh is not successful or the PostGIS sync raises an unexpected error.
- Does not start FastAPI.
- Does not create a background thread.
- Does not modify systemd files in this phase.

Refactored callable entrypoints:

- `backend.wior_refresh_job.run_wior_refresh_job()`
- `scripts.sync_wior_to_postgis.sync_wior_to_postgis(apply=False, reset_wior_postgis=False, dry_run=True, wior_db=None)`

Existing commands still work:

```powershell
py -3 -m backend.wior_refresh_job
py -3 scripts/sync_wior_to_postgis.py --apply
```

The PostGIS sync script remains the CLI for manual dry-run/apply use, and the combined job imports its callable function instead of duplicating sync SQL.

Skip-sync optimization:

- Phase 9C always syncs PostGIS after a successful WIOR refresh.
- The current WIOR refresh result reports loaded row counts but not a reliable changed-row signal.
- Correctness is preferred over a small optimization until a clean WIOR serving fingerprint or sync metadata table is added.

Phase 9C test helper:

- `scripts/test_wior_refresh_and_sync_job.py`

It checks that the combined job succeeds with `DATABASE_URL` set, `backend/wior.db` remains present, `backend/data/app.db` is not modified, `wior_work_areas` has mirrored rows, the default WIOR conflict endpoint still works through PostGIS, and `backend=legacy` remains available.

Future EC2/systemd update, documented only:

```ini
ExecStart=/home/ubuntu/apps/amsterdam-map-app/.venv/bin/python -m backend.wior_refresh_and_sync_job
```

When applied later, `wior-refresh.service` can change from:

```ini
ExecStart=/home/ubuntu/apps/amsterdam-map-app/.venv/bin/python -m backend.wior_refresh_job
```

to the combined job above. Do not move WIOR refresh into FastAPI startup, and do not run one refresh per Uvicorn worker. `backend/wior.db` remains the source/fallback cache. PostGIS `wior_work_areas` remains the conflict-query mirror.

Validation commands:

```powershell
$env:DATABASE_URL="postgresql://gvb_user:change_me@localhost:5432/gvb_map"
$env:APP_DB_BACKEND="postgres"

# Existing separate commands should still work.
py -3 -m backend.wior_refresh_job
py -3 scripts/sync_wior_to_postgis.py --apply

# New combined job.
py -3 -m backend.wior_refresh_and_sync_job

# Check WIOR mirror and conflicts.
py -3 scripts/check_postgis_data.py
py -3 scripts/compare_wior_conflicts.py
py -3 scripts/test_wior_conflict_modes.py

# New combined-job test.
py -3 scripts/test_wior_refresh_and_sync_job.py

# Regression tests.
py -3 scripts/test_api_click_modes.py
py -3 scripts/test_postgres_write_mode.py

# Compile.
py -3 -m py_compile backend/wior_refresh_job.py backend/wior_refresh_and_sync_job.py scripts/sync_wior_to_postgis.py scripts/test_wior_refresh_and_sync_job.py backend/main.py backend/postgis_wior_queries.py

# Health.
py -3 -c "import backend.main as m; print(m.health_check())"
```

## Phase 10 Audit Logs, Activity Views, And Settings Activity

Phase 10 uses one physical PostgreSQL table:

- `audit_logs`

The schema now safely adds these columns when missing:

- `actor_email`
- `actor_type`
- `action_scope`
- `action`
- `entity_type`
- `entity_id`
- `old_value`
- `new_value`
- `metadata`
- `ip_address`
- `user_agent`
- `created_at`

Logical activity views:

- `user_activity_view`: rows where `action_scope = 'user_action'`
- `admin_activity_view`: rows where `action_scope = 'admin_action'`
- `system_activity_view`: rows where `action_scope = 'system_action'`

Added indexes:

- `audit_logs_actor_email_created_at_idx`
- `audit_logs_action_scope_created_at_idx`
- `audit_logs_entity_idx`
- `audit_logs_action_created_at_idx`
- existing `audit_logs_created_at_idx`

Backend helper:

- `backend/audit_logs.py`

The helper uses synchronous psycopg3, writes only when PostgreSQL is configured, accepts an existing connection when provided, sanitizes sensitive keys, and never logs passwords, password hashes, full uploaded file contents, or raw request bodies. In SQLite/default mode, audit logging remains a safe no-op/fallback and does not break runtime behavior.

Audited PostgreSQL-mode actions:

- `login_success`
- `login_failed`
- `application_submitted`
- `file_upload_metadata_saved`
- `transfer_trip_submitted`
- `application_status_changed`
- `application_deleted`
- `transfer_trip_status_changed`
- `transfer_trip_deleted`
- `tbgn_project_created`
- `tbgn_project_updated`
- `tbgn_project_deleted`
- `wior_conflict_checked`
- `wior_postgis_fallback_to_legacy`
- `wior_refresh_and_sync_completed`
- `wior_refresh_and_sync_failed`

Status changes store small `old_value` and `new_value` objects such as:

```json
{"status": "submitted"}
```

Deletes store small safe metadata such as:

```json
{"deleted_entity_id": "..."}
```

WIOR conflict audit metadata is intentionally small:

- backend used
- fallback flag/reason when applicable
- conflict count
- target count

It does not log geometries or raw WIOR payloads.

Activity endpoints:

- `GET /api/settings/activity`
  - Requires a logged-in user.
  - Returns only rows for the current session email.
  - Supports `limit`, `offset`, and `action_scope`.
  - Default limit is 50, max 200.

- `GET /api/admin/audit-logs`
  - Admin only.
  - Supports `actor_email`, `action_scope`, `entity_type`, `entity_id`, `limit`, and `offset`.
  - Default limit is 100, max 500.

Frontend Settings UI:

- The user/admin account dropdown now includes `Settings`.
- Settings opens an Activity section.
- Activity calls `GET /api/settings/activity`.
- It shows date/time, action summary, entity type, and entity ID.
- Empty state: `No activity recorded yet.`
- Error state: `Could not load activity.`
- Raw JSON is not shown by default.

Important runtime scope:

- Audit logs are primarily a PostgreSQL-mode runtime feature.
- `APP_DB_BACKEND=sqlite` remains the safe fallback.
- SQLite fallback is not removed.
- Legacy WIOR fallback is not removed.
- No asyncpg or pgRouting has been added.

Validation commands:

```powershell
$env:DATABASE_URL="postgresql://gvb_user:change_me@localhost:5432/gvb_map"
$env:APP_DB_BACKEND="postgres"

py -3 scripts/init_postgis_schema.py

py -3 scripts/test_audit_logs.py
py -3 scripts/test_postgres_write_mode.py
py -3 scripts/test_wior_conflict_modes.py
py -3 scripts/test_wior_refresh_and_sync_job.py
py -3 scripts/test_api_click_modes.py

py -3 -m py_compile backend/main.py backend/audit_logs.py backend/postgres_app_queries.py backend/postgis_wior_queries.py scripts/test_audit_logs.py

py -3 -c "import backend.main as m; print(m.health_check())"
```

## Phase 11 Full Local PostgreSQL/PostGIS Verification

Phase 11 adds a local verification wrapper and deployment-readiness documentation before EC2 work starts.

Added:

- `scripts/verify_phase11_local.py`
- `docs/phase11_local_verification_checklist.md`
- `docs/ec2_github_deployment_precheck.md`

The verification script assumes `DATABASE_URL` is set and the local PostGIS container is running. It directly checks PostgreSQL reachability, schema objects, static GIS row counts, WIOR mirror rows, relational mirror freshness, PostgreSQL health, SQLite fallback health, and then runs the existing individual verification scripts in order.

Run:

```powershell
$env:DATABASE_URL="postgresql://gvb_user:change_me@localhost:5432/gvb_map"
$env:APP_DB_BACKEND="postgres"

py -3 scripts/verify_phase11_local.py
```

The manual browser checklist covers login, map loading, KGE selection, apply wizard, WIOR warning, application/admin flows, Settings -> Activity, transfers, TBGN, `/api/click`, WIOR conflict backend modes, and SQLite fallback.

The EC2 GitHub precheck document covers secret review, `.env` safety, database/upload file handling, scripts/assets/docs readiness, future EC2 setup order, and production risks. It explicitly warns not to overwrite EC2 `backend/data/app.db` or `backend/data/uploads`, and notes that `backend/wior.db` is safe to rebuild.

No EC2 deployment or systemd changes are made in Phase 11.

## Remaining Phases

1. Phase 13: perform documented cutover and rollback for the EC2 prototype.
2. Phase 14: remove legacy code only after the PostgreSQL version is stable.
