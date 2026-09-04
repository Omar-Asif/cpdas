-- CPDAS database schema.
--
-- Five read-only input tables (parcels, scans, riders, zones, deposits) plus one
-- append-only computed-output table (zone_assignments). The running Flask app
-- never INSERTs, UPDATEs, or DELETEs rows in the five input tables -- they are
-- populated exactly once, offline, by scripts/seed.py. See docs/SPEC_DECISIONS.md,
-- decision D10.5, for why that is not a violation of the no-CRUD constraint.
--
-- Note the deliberate absence of a "parcels.assigned_zone" column. The faculty
-- PDF mentions one, but storing the assigned zone directly on the parcels row
-- would force an UPDATE the first time a parcel is matched. zone_assignments
-- replaces it with an append-only audit trail instead. See decision D2.

CREATE TABLE zones (
    zone_id      TEXT PRIMARY KEY,      -- 'Z-MIR'
    zone_name    TEXT NOT NULL,         -- 'Mirpur'
    hub          TEXT NOT NULL,         -- 'Mirpur hub'
    description  TEXT NOT NULL          -- free text: areas, landmarks, spelling variants
);

CREATE TABLE riders (
    rider_id     TEXT PRIMARY KEY,      -- 'RD-114'
    name         TEXT NOT NULL,
    home_zone    TEXT NOT NULL REFERENCES zones(zone_id),
    duty_days    INTEGER NOT NULL       -- duty days in the reporting period
);

CREATE TABLE parcels (
    parcel_id         TEXT PRIMARY KEY,  -- 'PC-77012'
    booked_at         TEXT NOT NULL,     -- ISO 8601 'YYYY-MM-DD HH:MM:SS'
    promised_hours    INTEGER NOT NULL,  -- e.g. 48
    delivery_address  TEXT NOT NULL,     -- free text
    cod_amount        REAL NOT NULL      -- 0 for prepaid
);

CREATE TABLE scans (
    scan_id        INTEGER PRIMARY KEY,
    parcel_id      TEXT NOT NULL REFERENCES parcels(parcel_id),
    scan_type      TEXT NOT NULL CHECK (scan_type IN ('hub_out','delivered','failed_attempt')),
    rider_id       TEXT NOT NULL REFERENCES riders(rider_id),
    scanned_at     TEXT NOT NULL,
    failure_reason TEXT                  -- NULL unless scan_type = 'failed_attempt'
);

CREATE TABLE deposits (
    rider_id     TEXT NOT NULL REFERENCES riders(rider_id),
    deposit_date TEXT NOT NULL,         -- 'YYYY-MM-DD'
    amount       REAL NOT NULL,
    PRIMARY KEY (rider_id, deposit_date)
);

-- Computed output only. INSERT-only. See decision D2.
CREATE TABLE zone_assignments (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    parcel_id        TEXT NOT NULL REFERENCES parcels(parcel_id),
    zone_id          TEXT REFERENCES zones(zone_id),   -- NULL = manual sorting queue
    similarity_score REAL NOT NULL,
    source           TEXT NOT NULL CHECK (source IN ('auto','manual')),
    created_at       TEXT NOT NULL
);

CREATE INDEX idx_scans_parcel_id ON scans(parcel_id);
CREATE INDEX idx_scans_rider_id ON scans(rider_id);
CREATE INDEX idx_scans_scanned_at ON scans(scanned_at);
CREATE INDEX idx_zone_assignments_parcel_id ON zone_assignments(parcel_id);
