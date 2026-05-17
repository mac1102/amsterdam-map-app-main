# EC2 GitHub Deployment Precheck

This is a precheck document only. Phase 11 does not deploy to EC2 and does not edit systemd files.

## GitHub Readiness Checklist

Run before pushing or preparing an EC2 pull:

```powershell
git status
```

Confirm:

- No accidental secrets are staged.
- `.env` is not committed.
- `.env.example` contains only safe placeholder values.
- No real database password is committed.
- `backend/data/app.db` handling is intentional.
- `backend/data/uploads` handling is intentional.
- `backend/wior.db` can be rebuilt from the WIOR refresh job.
- `requirements.txt` includes all needed Python packages.
- `docker-compose.yml` is present.
- `database/schema_postgres.sql` is present.
- Migration, import, WIOR, audit, and verification scripts are committed.
- Static assets needed by the frontend are committed.
- Documentation is updated.

## EC2 Data Safety

Do not overwrite these on EC2:

- `backend/data/app.db`
- `backend/data/uploads`

Safe to rebuild if needed:

- `backend/wior.db`

`backend/wior.db` remains the WIOR refresh/cache source and fallback cache. The PostGIS `wior_work_areas` table is the query mirror used by the PostGIS conflict engine.

## Production Risk Notes

- `APP_DB_BACKEND=postgres` writes only to PostgreSQL.
- Rows written in PostgreSQL mode will not automatically appear in SQLite.
- Rollback to `APP_DB_BACKEND=sqlite` works, but PostgreSQL-only data will not appear in SQLite unless copied back.
- Before EC2 cutover, run a final migration from SQLite to PostgreSQL.
- After WIOR refresh, the PostGIS mirror must be synced. The Phase 9C combined job handles this.
- Do not expose PostgreSQL port `5432` publicly.
- Keep PostgreSQL local to EC2 for now.
- Use an SSH tunnel and DBeaver or `psql` if remote DB inspection is needed.
- Do not move WIOR refresh into FastAPI startup.
- Do not run one WIOR refresh per Uvicorn worker.

## Future EC2 High-Level Sequence

Notes only; do not apply in Phase 11.

1. Clone/pull the GitHub repo into a new folder, or update the existing folder carefully.
2. Install Python requirements.
3. Start PostGIS with Docker Compose.
4. Set `DATABASE_URL`.
5. Run schema/init scripts.
6. Import static GIS.
7. Run a final SQLite-to-PostgreSQL migration if cutting over.
8. Run the combined WIOR refresh + PostGIS sync job.
9. Set `APP_DB_BACKEND` after deciding `sqlite` versus `postgres`.
10. Restart `gvb-map.service`.
11. Later update `wior-refresh.service` to use:

```text
python -m backend.wior_refresh_and_sync_job
```

12. Restart and check systemd services.

Suggested future `ExecStart` for the WIOR refresh service:

```ini
ExecStart=/home/ubuntu/apps/amsterdam-map-app/.venv/bin/python -m backend.wior_refresh_and_sync_job
```

Again: do not edit EC2 systemd files in Phase 11.

## Local Verification Before Push

Run:

```powershell
$env:DATABASE_URL="postgresql://gvb_user:change_me@localhost:5432/gvb_map"
$env:APP_DB_BACKEND="postgres"

py -3 scripts/verify_phase11_local.py
```

Then complete:

- `docs/phase11_local_verification_checklist.md`
