"""Database connection helper for CPDAS.

Every module function receives a plain sqlite3.Connection from here. The five
input tables (parcels, scans, riders, zones, deposits) are only ever read by
the application; the sole write path anywhere in this file's callers is an
INSERT into zone_assignments (see modules/m4_matching.py and decision D2 in
docs/SPEC_DECISIONS.md).
"""

import sqlite3
from pathlib import Path

# The database lives next to this file, so the app works regardless of the
# directory the interpreter was launched from.
DB_PATH = Path(__file__).resolve().parent / "cpdas.db"


def get_connection():
    """Open a connection to the CPDAS SQLite database.

    Rows are returned as sqlite3.Row objects so callers can access columns by
    name (row["zone_id"]) as well as by position.
    """
    connection = sqlite3.connect(DB_PATH)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    return connection
