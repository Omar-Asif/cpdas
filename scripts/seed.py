"""Build the CPDAS SQLite database from schema.sql and the CSVs in data/.

Run this once, after scripts/generate_data.py, to create cpdas.db. Like
generate_data.py, this is the one-time, offline data hand-off described in
decision D10.5 of docs/SPEC_DECISIONS.md -- it is the only place in the whole
project that ever writes to the five input tables (parcels, scans, riders,
zones, deposits), and it never runs while the web server is serving requests.
scripts/verify.py's CRUD audit excludes this file for exactly that reason.
"""

import csv
import sqlite3
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "data"
SCHEMA_PATH = PROJECT_ROOT / "schema.sql"
DB_PATH = PROJECT_ROOT / "cpdas.db"


def read_csv_rows(filename):
    path = DATA_DIR / filename
    with open(path, newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def load_zones(connection):
    rows = read_csv_rows("zones.csv")
    connection.executemany(
        "INSERT INTO zones (zone_id, zone_name, hub, description) VALUES (?, ?, ?, ?)",
        [(r["zone_id"], r["zone_name"], r["hub"], r["description"]) for r in rows],
    )
    print(f"loaded {len(rows):>6} zones")


def load_riders(connection):
    rows = read_csv_rows("riders.csv")
    connection.executemany(
        "INSERT INTO riders (rider_id, name, home_zone, duty_days) VALUES (?, ?, ?, ?)",
        [(r["rider_id"], r["name"], r["home_zone"], int(r["duty_days"])) for r in rows],
    )
    print(f"loaded {len(rows):>6} riders")


def load_parcels(connection):
    rows = read_csv_rows("parcels.csv")
    connection.executemany(
        "INSERT INTO parcels (parcel_id, booked_at, promised_hours, delivery_address, cod_amount) "
        "VALUES (?, ?, ?, ?, ?)",
        [
            (r["parcel_id"], r["booked_at"], int(r["promised_hours"]), r["delivery_address"], float(r["cod_amount"]))
            for r in rows
        ],
    )
    print(f"loaded {len(rows):>6} parcels")


def load_scans(connection):
    rows = read_csv_rows("scans.csv")
    connection.executemany(
        "INSERT INTO scans (scan_id, parcel_id, scan_type, rider_id, scanned_at, failure_reason) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        [
            (
                int(r["scan_id"]), r["parcel_id"], r["scan_type"], r["rider_id"], r["scanned_at"],
                r["failure_reason"] if r["failure_reason"] else None,
            )
            for r in rows
        ],
    )
    print(f"loaded {len(rows):>6} scans")


def load_deposits(connection):
    rows = read_csv_rows("deposits.csv")
    connection.executemany(
        "INSERT INTO deposits (rider_id, deposit_date, amount) VALUES (?, ?, ?)",
        [(r["rider_id"], r["deposit_date"], float(r["amount"])) for r in rows],
    )
    print(f"loaded {len(rows):>6} deposits")


def load_zone_assignments(connection):
    """Pre-populate zone_assignments for historical parcels only.

    These rows represent parcels that were already matched and dispatched as
    part of normal past operations -- the same "already recorded" framing
    decision D10.5 applies to the other four input datasets. The M4
    demonstration parcels (PC-77012 and friends) are deliberately excluded
    from data/zone_assignments.csv by generate_data.py, so they remain in
    the unmatched state the M4 module's live "Run AI Matching" demo needs.
    """
    rows = read_csv_rows("zone_assignments.csv")
    connection.executemany(
        "INSERT INTO zone_assignments (parcel_id, zone_id, similarity_score, source, created_at) "
        "VALUES (?, ?, ?, ?, ?)",
        [
            (r["parcel_id"], r["zone_id"] or None, float(r["similarity_score"]), r["source"], r["created_at"])
            for r in rows
        ],
    )
    print(f"loaded {len(rows):>6} zone_assignments")


def main():
    if not SCHEMA_PATH.exists():
        sys.exit(f"schema.sql not found at {SCHEMA_PATH}")
    if not DATA_DIR.exists() or not any(DATA_DIR.glob("*.csv")):
        sys.exit(f"No CSVs found in {DATA_DIR} -- run scripts/generate_data.py first.")

    if DB_PATH.exists():
        DB_PATH.unlink()
        print(f"removed existing {DB_PATH}")

    connection = sqlite3.connect(DB_PATH)
    try:
        connection.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
        connection.execute("PRAGMA foreign_keys = ON")

        load_zones(connection)
        load_riders(connection)
        load_parcels(connection)
        load_scans(connection)
        load_deposits(connection)
        load_zone_assignments(connection)

        connection.commit()
        print()
        print(f"Database built at {DB_PATH}")
    finally:
        connection.close()


if __name__ == "__main__":
    main()
