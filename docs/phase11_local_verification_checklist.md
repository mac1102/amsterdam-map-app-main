# Phase 11 Local Verification Checklist

Use this checklist after the automated Phase 11 commands pass. It covers browser-only behavior that script tests cannot fully prove.

## Start PostgreSQL Mode Locally

PowerShell:

```powershell
$env:DATABASE_URL="postgresql://gvb_user:change_me@localhost:5432/gvb_map"
$env:APP_DB_BACKEND="postgres"
uvicorn backend.main:app --reload
```

Open:

```text
http://127.0.0.1:8000
```

## Browser Checks In PostgreSQL Mode

- `/health` shows `status = ok`.
- `/health` shows `app_db_backend.resolved = postgres`.
- `/health` shows PostgreSQL configured and available.
- Login works.
- Map loads.
- KGE segment selection works.
- Apply wizard opens from a selected segment.
- Apply wizard planning/contact/upload flow works.
- Step 4/Review WIOR conflict warning appears for a known conflicting target/date.
- Submit a test application.
- My applications shows the submitted application.
- Admin applications shows the submitted application.
- Admin approve/decline works.
- Settings appears in the user/admin dropdown.
- Settings -> Activity shows activity records.
- Activity list does not show raw JSON, passwords, or password hashes.
- Admin audit endpoint works if tested:

```powershell
Invoke-RestMethod -Method Get -Uri "http://127.0.0.1:8000/api/admin/audit-logs?limit=20" -WebSession $session
```

- Transfer trip flow works.
- TBGN create/update/delete works.
- `/api/click` old `x/y` mode still works.
- `/api/click` new `lng/lat` mode still works.

## WIOR Conflict Endpoint Modes

Use an authenticated browser/session or API client and verify:

- `POST /api/wior/conflicts/check` uses default PostGIS-first mode.
- `POST /api/wior/conflicts/check?backend=legacy` uses legacy WIOR logic.
- `POST /api/wior/conflicts/check?backend=postgis` uses only PostGIS.
- `POST /api/wior/conflicts/check?backend=compare` returns both legacy and PostGIS results.

Default response shape must still include:

- `ok`
- `has_conflicts`
- `conflict_count`
- `conflicts`

## SQLite Fallback Check

Stop the dev server, then restart with SQLite mode:

```powershell
$env:APP_DB_BACKEND="sqlite"
uvicorn backend.main:app --reload
```

Check:

- `/health` shows `app_db_backend.resolved = sqlite`.
- Login still works.
- Map loads.
- Existing SQLite application path still works.
- `/api/click` old `x/y` mode still works.
- Legacy WIOR fallback remains available.

## Notes

- PostgreSQL-mode writes go only to PostgreSQL.
- SQLite fallback works, but PostgreSQL-only data will not automatically appear in SQLite.
- Before EC2 cutover, run a final SQLite-to-PostgreSQL migration.
- Do not move WIOR refresh into FastAPI startup.
- Do not run one WIOR refresh per Uvicorn worker.
