CREATE EXTENSION IF NOT EXISTS postgis;
CREATE EXTENSION IF NOT EXISTS pgcrypto;

CREATE TABLE IF NOT EXISTS users (
    email TEXT PRIMARY KEY,
    password_hash TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    is_admin BOOLEAN NOT NULL DEFAULT false
);

CREATE TABLE IF NOT EXISTS tram_lines (
    line_id TEXT PRIMARY KEY,
    line_name TEXT,
    mode TEXT NOT NULL DEFAULT 'tram',
    color TEXT,
    source TEXT NOT NULL DEFAULT 'official_kge',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS tram_segments (
    id BIGSERIAL PRIMARY KEY,
    segment_id TEXT UNIQUE NOT NULL,
    line_id TEXT REFERENCES tram_lines(line_id) ON UPDATE CASCADE ON DELETE SET NULL,
    line_name TEXT,
    source TEXT NOT NULL DEFAULT 'official_kge',
    bookable BOOLEAN NOT NULL DEFAULT true,
    geom geometry(MultiLineString, 4326) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS tram_stops (
    id BIGSERIAL PRIMARY KEY,
    stop_id TEXT UNIQUE NOT NULL,
    stop_name TEXT,
    stop_type TEXT,
    source TEXT NOT NULL DEFAULT 'official_kge',
    raw_modaliteit TEXT,
    raw_lijn TEXT,
    raw_lijn_select TEXT,
    current_display_lijn TEXT,
    current_display_lijn_select TEXT,
    valid_tram_lijn TEXT,
    valid_tram_lijn_select TEXT,
    is_current_frontend_visible BOOLEAN NOT NULL DEFAULT false,
    is_valid_tram_line_stop BOOLEAN NOT NULL DEFAULT false,
    geom geometry(Point, 4326) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

ALTER TABLE tram_stops
ADD COLUMN IF NOT EXISTS raw_modaliteit TEXT;

ALTER TABLE tram_stops
ADD COLUMN IF NOT EXISTS raw_lijn TEXT;

ALTER TABLE tram_stops
ADD COLUMN IF NOT EXISTS raw_lijn_select TEXT;

ALTER TABLE tram_stops
ADD COLUMN IF NOT EXISTS current_display_lijn TEXT;

ALTER TABLE tram_stops
ADD COLUMN IF NOT EXISTS current_display_lijn_select TEXT;

ALTER TABLE tram_stops
ADD COLUMN IF NOT EXISTS valid_tram_lijn TEXT;

ALTER TABLE tram_stops
ADD COLUMN IF NOT EXISTS valid_tram_lijn_select TEXT;

ALTER TABLE tram_stops
ADD COLUMN IF NOT EXISTS is_current_frontend_visible BOOLEAN NOT NULL DEFAULT false;

ALTER TABLE tram_stops
ADD COLUMN IF NOT EXISTS is_valid_tram_line_stop BOOLEAN NOT NULL DEFAULT false;

ALTER TABLE tram_stops
ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ DEFAULT now();

CREATE TABLE IF NOT EXISTS applications (
    application_id TEXT PRIMARY KEY DEFAULT gen_random_uuid()::text,
    submitted_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    status TEXT NOT NULL,
    submitted_by_email TEXT NOT NULL REFERENCES users(email) ON UPDATE CASCADE ON DELETE CASCADE,
    person_mode TEXT NOT NULL,
    work_description TEXT,
    work_source TEXT,
    urgency TEXT,
    affected_lines TEXT,
    work_notes TEXT,
    coordinator TEXT,
    vvw_measure TEXT,
    project_start TIMESTAMPTZ,
    project_end TIMESTAMPTZ,
    admin_note TEXT DEFAULT '',
    decision_message TEXT DEFAULT ''
);

CREATE TABLE IF NOT EXISTS application_targets (
    id BIGSERIAL PRIMARY KEY,
    application_id TEXT NOT NULL REFERENCES applications(application_id) ON UPDATE CASCADE ON DELETE CASCADE,
    target_index INTEGER NOT NULL,
    target_type TEXT NOT NULL DEFAULT 'rail_segment',
    asset_id TEXT,
    asset_label TEXT,
    asset_source TEXT,
    segment_id TEXT REFERENCES tram_segments(segment_id) ON UPDATE CASCADE ON DELETE RESTRICT,
    line_id TEXT,
    line_name TEXT,
    work_mode TEXT NOT NULL,
    work_start_x INTEGER,
    work_start_y INTEGER,
    work_end_x INTEGER,
    work_end_y INTEGER,
    project_start TIMESTAMPTZ NOT NULL,
    project_end TIMESTAMPTZ NOT NULL
);

CREATE TABLE IF NOT EXISTS application_target_windows (
    id BIGSERIAL PRIMARY KEY,
    target_id BIGINT NOT NULL REFERENCES application_targets(id) ON UPDATE CASCADE ON DELETE CASCADE,
    window_index INTEGER NOT NULL,
    project_start TIMESTAMPTZ NOT NULL,
    project_end TIMESTAMPTZ NOT NULL,
    label TEXT
);

CREATE TABLE IF NOT EXISTS application_people (
    id BIGSERIAL PRIMARY KEY,
    application_id TEXT NOT NULL REFERENCES applications(application_id) ON UPDATE CASCADE ON DELETE CASCADE,
    target_index INTEGER,
    first_name TEXT NOT NULL,
    last_name TEXT NOT NULL,
    phone TEXT NOT NULL,
    email TEXT NOT NULL,
    employee_id TEXT
);

CREATE TABLE IF NOT EXISTS application_uploads (
    id BIGSERIAL PRIMARY KEY,
    application_id TEXT NOT NULL REFERENCES applications(application_id) ON UPDATE CASCADE ON DELETE CASCADE,
    original_filename TEXT NOT NULL,
    stored_filename TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS transfer_trips (
    transfer_trip_id TEXT PRIMARY KEY DEFAULT gen_random_uuid()::text,
    submitted_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    status TEXT NOT NULL DEFAULT 'submitted',
    submitted_by_email TEXT NOT NULL REFERENCES users(email) ON UPDATE CASCADE ON DELETE CASCADE,
    start_stop_id INTEGER NOT NULL,
    start_stop_name TEXT NOT NULL,
    end_stop_id INTEGER NOT NULL,
    end_stop_name TEXT NOT NULL,
    planned_date DATE NOT NULL,
    planned_start_time TEXT NOT NULL,
    planned_end_time TEXT NOT NULL,
    tram_number TEXT,
    reason TEXT,
    notes TEXT,
    route_distance_m DOUBLE PRECISION,
    route_geometry JSONB,
    admin_note TEXT DEFAULT '',
    decision_message TEXT DEFAULT ''
);

CREATE TABLE IF NOT EXISTS transfer_trip_points (
    id BIGSERIAL PRIMARY KEY,
    transfer_trip_id TEXT NOT NULL REFERENCES transfer_trips(transfer_trip_id) ON UPDATE CASCADE ON DELETE CASCADE,
    point_index INTEGER NOT NULL,
    segment_id TEXT REFERENCES tram_segments(segment_id) ON UPDATE CASCADE ON DELETE SET NULL,
    lng DOUBLE PRECISION NOT NULL,
    lat DOUBLE PRECISION NOT NULL
);

CREATE TABLE IF NOT EXISTS tbgn_projects (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    start_date DATE NOT NULL,
    end_date DATE NOT NULL,
    affected_lines TEXT,
    color TEXT DEFAULT '#7c3aed',
    geometry TEXT,
    status TEXT NOT NULL DEFAULT 'draft',
    notes TEXT,
    created_by TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS wior_work_areas (
    id BIGSERIAL PRIMARY KEY,
    application_id TEXT REFERENCES applications(application_id) ON UPDATE CASCADE ON DELETE SET NULL,
    wior_id TEXT,
    wior_reference TEXT,
    title TEXT,
    source TEXT,
    area_type TEXT,
    description TEXT,
    status TEXT,
    start_date TIMESTAMPTZ,
    end_date TIMESTAMPTZ,
    raw_payload JSONB,
    segment_ids JSONB,
    is_active BOOLEAN NOT NULL DEFAULT false,
    is_upcoming_7d BOOLEAN NOT NULL DEFAULT false,
    is_upcoming_30d BOOLEAN NOT NULL DEFAULT false,
    is_expired BOOLEAN NOT NULL DEFAULT false,
    is_near_tram BOOLEAN NOT NULL DEFAULT false,
    last_built_at TIMESTAMPTZ,
    geom geometry(Geometry, 4326),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

ALTER TABLE wior_work_areas
ADD COLUMN IF NOT EXISTS wior_id TEXT;

ALTER TABLE wior_work_areas
ADD COLUMN IF NOT EXISTS wior_reference TEXT;

ALTER TABLE wior_work_areas
ADD COLUMN IF NOT EXISTS title TEXT;

ALTER TABLE wior_work_areas
ADD COLUMN IF NOT EXISTS status TEXT;

ALTER TABLE wior_work_areas
ADD COLUMN IF NOT EXISTS start_date TIMESTAMPTZ;

ALTER TABLE wior_work_areas
ADD COLUMN IF NOT EXISTS end_date TIMESTAMPTZ;

ALTER TABLE wior_work_areas
ADD COLUMN IF NOT EXISTS raw_payload JSONB;

ALTER TABLE wior_work_areas
ADD COLUMN IF NOT EXISTS segment_ids JSONB;

ALTER TABLE wior_work_areas
ADD COLUMN IF NOT EXISTS is_active BOOLEAN NOT NULL DEFAULT false;

ALTER TABLE wior_work_areas
ADD COLUMN IF NOT EXISTS is_upcoming_7d BOOLEAN NOT NULL DEFAULT false;

ALTER TABLE wior_work_areas
ADD COLUMN IF NOT EXISTS is_upcoming_30d BOOLEAN NOT NULL DEFAULT false;

ALTER TABLE wior_work_areas
ADD COLUMN IF NOT EXISTS is_expired BOOLEAN NOT NULL DEFAULT false;

ALTER TABLE wior_work_areas
ADD COLUMN IF NOT EXISTS is_near_tram BOOLEAN NOT NULL DEFAULT false;

ALTER TABLE wior_work_areas
ADD COLUMN IF NOT EXISTS last_built_at TIMESTAMPTZ;

ALTER TABLE wior_work_areas
ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ DEFAULT now();

CREATE TABLE IF NOT EXISTS audit_logs (
    id BIGSERIAL PRIMARY KEY,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    actor_email TEXT,
    actor_type TEXT,
    action_scope TEXT,
    action TEXT NOT NULL,
    entity_type TEXT,
    entity_id TEXT,
    old_value JSONB,
    new_value JSONB,
    metadata JSONB,
    ip_address TEXT,
    user_agent TEXT,
    details JSONB
);

ALTER TABLE audit_logs
ADD COLUMN IF NOT EXISTS actor_email TEXT;

ALTER TABLE audit_logs
ADD COLUMN IF NOT EXISTS actor_type TEXT;

ALTER TABLE audit_logs
ADD COLUMN IF NOT EXISTS action_scope TEXT;

ALTER TABLE audit_logs
ADD COLUMN IF NOT EXISTS action TEXT;

ALTER TABLE audit_logs
ADD COLUMN IF NOT EXISTS entity_type TEXT;

ALTER TABLE audit_logs
ADD COLUMN IF NOT EXISTS entity_id TEXT;

ALTER TABLE audit_logs
ADD COLUMN IF NOT EXISTS old_value JSONB;

ALTER TABLE audit_logs
ADD COLUMN IF NOT EXISTS new_value JSONB;

ALTER TABLE audit_logs
ADD COLUMN IF NOT EXISTS metadata JSONB;

ALTER TABLE audit_logs
ADD COLUMN IF NOT EXISTS ip_address TEXT;

ALTER TABLE audit_logs
ADD COLUMN IF NOT EXISTS user_agent TEXT;

ALTER TABLE audit_logs
ADD COLUMN IF NOT EXISTS created_at TIMESTAMPTZ DEFAULT now();

CREATE INDEX IF NOT EXISTS tram_segments_geom_idx
ON tram_segments
USING GIST (geom);

CREATE INDEX IF NOT EXISTS tram_stops_geom_idx
ON tram_stops
USING GIST (geom);

CREATE INDEX IF NOT EXISTS wior_work_areas_geom_idx
ON wior_work_areas
USING GIST (geom);

CREATE UNIQUE INDEX IF NOT EXISTS wior_work_areas_wior_id_uidx
ON wior_work_areas(wior_id)
WHERE wior_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS wior_work_areas_dates_idx
ON wior_work_areas(start_date, end_date);

CREATE INDEX IF NOT EXISTS wior_work_areas_status_idx
ON wior_work_areas(status);

CREATE INDEX IF NOT EXISTS applications_status_idx
ON applications(status);

CREATE INDEX IF NOT EXISTS applications_dates_idx
ON applications(project_start, project_end);

CREATE INDEX IF NOT EXISTS application_targets_segment_idx
ON application_targets(segment_id);

CREATE INDEX IF NOT EXISTS application_targets_application_idx
ON application_targets(application_id);

CREATE INDEX IF NOT EXISTS audit_logs_created_at_idx
ON audit_logs(created_at);

CREATE INDEX IF NOT EXISTS audit_logs_actor_email_created_at_idx
ON audit_logs(actor_email, created_at DESC);

CREATE INDEX IF NOT EXISTS audit_logs_action_scope_created_at_idx
ON audit_logs(action_scope, created_at DESC);

CREATE INDEX IF NOT EXISTS audit_logs_entity_idx
ON audit_logs(entity_type, entity_id);

CREATE INDEX IF NOT EXISTS audit_logs_action_created_at_idx
ON audit_logs(action, created_at DESC);

CREATE OR REPLACE VIEW user_activity_view AS
SELECT *
FROM audit_logs
WHERE action_scope = 'user_action';

CREATE OR REPLACE VIEW admin_activity_view AS
SELECT *
FROM audit_logs
WHERE action_scope = 'admin_action';

CREATE OR REPLACE VIEW system_activity_view AS
SELECT *
FROM audit_logs
WHERE action_scope = 'system_action';

CREATE INDEX IF NOT EXISTS application_target_windows_target_idx
ON application_target_windows(target_id);

CREATE INDEX IF NOT EXISTS application_people_application_idx
ON application_people(application_id);

CREATE INDEX IF NOT EXISTS application_uploads_application_idx
ON application_uploads(application_id);

CREATE INDEX IF NOT EXISTS transfer_trips_email_idx
ON transfer_trips(submitted_by_email);

CREATE INDEX IF NOT EXISTS transfer_trip_points_trip_idx
ON transfer_trip_points(transfer_trip_id);
