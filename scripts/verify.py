"""Verification suite for CPDAS.

Runs against the seeded database (run scripts/generate_data.py and
scripts/seed.py first) and asserts every examined figure from the faculty
specification, using the SAME module functions the running application
calls -- so a failure here means the application itself would show the
wrong number, not just that some standalone check disagrees with it.

Also audits the codebase for CRUD violations against the five input tables
(parcels, scans, riders, zones, deposits): decision D10.5 says the running
application only ever writes there via scripts/seed.py's one-time offline
hand-off. tests/test_formulas.py is the one other exception -- it builds
its own throwaway in-memory SQLite database for unit testing and never
touches cpdas.db. This script greps the rest of the project to make sure
neither exception grows a third.

Exits with status 1 if anything fails; prints a pass/fail table either way.
"""

import re
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from db import get_connection
from modules import formatting, m1_delivery, m2_rider, m3_cod, m4_matching, m5_reports

RESULTS = []  # list of (description, passed, detail)


def check(description, passed, detail=""):
    RESULTS.append((description, bool(passed), detail))


# ---------------------------------------------------------------------------
# M1 / R1 -- Delivery Performance Analytics
# ---------------------------------------------------------------------------

def run_m1_checks(connection):
    mir = m1_delivery.get_zone_performance(connection, "Z-MIR", "2026-07-08")
    check("M1 Z-MIR success = 91.2%", formatting.format_percent(mir["success_pct"]) == "91.2%")
    check("M1 Z-MIR on-time = 89.9%", formatting.format_percent(mir["on_time_pct"]) == "89.9%")
    check("M1 Z-MIR avg delivery time = 33.0 h", formatting.format_hours(mir["avg_delivery_hours"]) == "33.0 h")
    check("M1 Z-MIR operations review flag = No", mir["operations_review_flag"] is False)

    utt = m1_delivery.get_zone_performance(connection, "Z-UTT", "2026-07-08")
    check("M1 Z-UTT success = 93.9%", formatting.format_percent(utt["success_pct"]) == "93.9%")
    check("M1 Z-UTT on-time = 92.5%", formatting.format_percent(utt["on_time_pct"]) == "92.5%")

    dhn = m1_delivery.get_zone_performance(connection, "Z-DHN", "2026-07-08")
    check("M1 Z-DHN success = 85.1%", formatting.format_percent(dhn["success_pct"]) == "85.1%")
    check("M1 Z-DHN on-time = 84.5%", formatting.format_percent(dhn["on_time_pct"]) == "84.5%")

    dhn_day6 = m1_delivery.get_zone_performance(connection, "Z-DHN", "2026-07-06")
    check(
        "M1 Z-DHN operations review flag = Yes on 06 July (3-day streak 04-06)",
        dhn_day6["operations_review_flag"] is True,
    )

    r1 = m5_reports.get_r1_report(connection, "2026-07-08")
    check("R1 totals attempted = 622", r1["totals"]["n_attempted"] == 622)
    check("R1 totals delivered = 562", r1["totals"]["n_delivered"] == 562)
    check("R1 totals failed = 60", r1["totals"]["n_failed"] == 60)
    check(
        "R1 top failure reason = customer unreachable (34 of 60)",
        r1["top_failure_reason"] == "customer unreachable"
        and r1["top_failure_reason_count"] == 34
        and r1["top_failure_reason_total_failed"] == 60,
    )


# ---------------------------------------------------------------------------
# R2 -- Zone Performance Report (7-day window, decision D7)
# ---------------------------------------------------------------------------

def run_r2_checks(connection):
    r2 = m5_reports.get_r2_report(connection, "2026-07-08")
    by_zone = {z["zone_id"]: z for z in r2["zones"]}

    check(
        "R2 Z-MIR: 33.0 h / 90.8% / volume 1702",
        formatting.format_hours(by_zone["Z-MIR"]["avg_delivery_hours"]) == "33.0 h"
        and formatting.format_percent(by_zone["Z-MIR"]["success_pct"]) == "90.8%"
        and by_zone["Z-MIR"]["volume"] == 1702,
    )
    check(
        "R2 Z-UTT: 29.4 h / 94.1% / volume 1310",
        formatting.format_hours(by_zone["Z-UTT"]["avg_delivery_hours"]) == "29.4 h"
        and formatting.format_percent(by_zone["Z-UTT"]["success_pct"]) == "94.1%"
        and by_zone["Z-UTT"]["volume"] == 1310,
    )
    check(
        "R2 Z-DHN: 41.6 h / 83.9% / volume 1166 / flagged day 3",
        formatting.format_hours(by_zone["Z-DHN"]["avg_delivery_hours"]) == "41.6 h"
        and formatting.format_percent(by_zone["Z-DHN"]["success_pct"]) == "83.9%"
        and by_zone["Z-DHN"]["volume"] == 1166
        and by_zone["Z-DHN"]["flag_day_index"] == 3,
    )
    check("R2 ISO week of 2026-07-08 is 28", r2["iso_week"] == 28)


# ---------------------------------------------------------------------------
# M2 / R3 -- Rider Productivity Analytics
# ---------------------------------------------------------------------------

def run_m2_checks(connection):
    rider_rows, mean_pi, threshold = m2_rider.get_all_rider_productivity(connection, "2026-06")
    by_id = {row["rider_id"]: row for row in rider_rows}

    check(
        "M2 RD-114: pi=21.2, FailRate=9.3%",
        formatting.format_number(by_id["RD-114"]["pi_r"]) == "21.2"
        and formatting.format_percent(by_id["RD-114"]["fail_rate_pct"]) == "9.3%",
    )
    check(
        "M2 RD-108: pi=18.9, FailRate=11.4%",
        formatting.format_number(by_id["RD-108"]["pi_r"]) == "18.9"
        and formatting.format_percent(by_id["RD-108"]["fail_rate_pct"]) == "11.4%",
    )
    check(
        "M2 RD-131: pi=12.9, FailRate=17.8%",
        formatting.format_number(by_id["RD-131"]["pi_r"]) == "12.9"
        and formatting.format_percent(by_id["RD-131"]["fail_rate_pct"]) == "17.8%",
    )
    check("M2 company mean pi-bar displays 19.5", formatting.format_number(mean_pi) == "19.5")
    check("M2 coaching threshold displays 13.7", formatting.format_number(threshold) == "13.7")
    check("M2 RD-131 is on the coaching list", by_id["RD-131"]["coaching_flag"] is True)
    check("M2 RD-114 is NOT on the coaching list", by_id["RD-114"]["coaching_flag"] is False)
    check("M2 RD-108 is NOT on the coaching list", by_id["RD-108"]["coaching_flag"] is False)


# ---------------------------------------------------------------------------
# M3 / R4 -- COD Reconciliation
# ---------------------------------------------------------------------------

def run_m3_checks(connection):
    rows = m3_cod.get_all_cod_reconciliation(connection, "2026-07-08")
    by_id = {row["rider_id"]: row for row in rows}

    for rider_id, expected_collected, expected_deposited, expected_delta in [
        ("RD-114", "38,450", "38,450", "0"),
        ("RD-108", "31,220", "31,220", "0"),
        ("RD-131", "27,300", "26,300", "1,000"),
    ]:
        row = by_id[rider_id]
        check(
            f"M3 {rider_id}: C_r={expected_collected}, G_r={expected_deposited}, delta={expected_delta}",
            formatting.format_currency(row["collected"]) == expected_collected
            and formatting.format_currency(row["deposited"]) == expected_deposited
            and formatting.format_currency(row["delta"]) == expected_delta,
        )

    r4 = m5_reports.get_r4_report(connection, "2026-07-08")
    check(
        "R4 totals: collected 96,970 / deposited 95,970 / shortage 1,000 (1 rider)",
        formatting.format_currency(r4["totals"]["collected"]) == "96,970"
        and formatting.format_currency(r4["totals"]["deposited"]) == "95,970"
        and formatting.format_currency(r4["totals"]["shortage"]) == "1,000"
        and r4["totals"]["riders_with_shortage"] == 1,
    )


# ---------------------------------------------------------------------------
# M4 -- AI Address-to-Zone Matching
# ---------------------------------------------------------------------------

def run_m4_checks(connection):
    parcel = connection.execute(
        "SELECT delivery_address FROM parcels WHERE parcel_id = 'PC-77012'"
    ).fetchone()
    scores = m4_matching.score_parcel_against_zones(connection, parcel["delivery_address"], use_tfidf=False)
    by_zone = {entry["zone_id"]: entry for entry in scores}

    check("M4 PC-77012 vs Z-MIR is exactly 0.80", abs(by_zone["Z-MIR"]["score"] - 0.80) < 1e-9)
    check("M4 PC-77012 vs Z-MIR is auto-assigned (meets threshold)", by_zone["Z-MIR"]["meets_threshold"] is True)
    check(
        "M4 PC-77012 second-best Z-UTT displays 16%",
        formatting.format_similarity_percent(by_zone["Z-UTT"]["score"]) == "16%",
    )

    resolved_zone_id, _ = m4_matching.resolve_auto_assignment(scores)
    check("M4 PC-77012 resolves to auto-assignment on Z-MIR", resolved_zone_id == "Z-MIR")

    below_threshold_scores = m4_matching.score_parcel_against_zones(connection, "near college gate, Dhaka", use_tfidf=False)
    check(
        "M4 'near college gate, Dhaka' scores below 0.80 against every zone",
        all(not entry["meets_threshold"] for entry in below_threshold_scores),
    )


# ---------------------------------------------------------------------------
# D3 invariant: attempted == delivered + failed, for every zone and date
# ---------------------------------------------------------------------------

def run_d3_invariant_check(connection):
    """Independent re-derivation (not calling modules.m1_delivery) of every
    parcel's resolved outcome per (zone, date), cross-checked against what
    m1_delivery.get_zone_performance actually returns for the same pairs.
    """
    scan_rows = connection.execute(
        "SELECT parcel_id, scan_type, scanned_at FROM scans WHERE scan_type IN ('delivered', 'failed_attempt')"
    ).fetchall()

    zone_by_parcel = {}
    for row in connection.execute(
        """
        SELECT parcel_id, zone_id FROM zone_assignments za
        WHERE id = (SELECT MAX(id) FROM zone_assignments WHERE parcel_id = za.parcel_id)
        """
    ):
        zone_by_parcel[row["parcel_id"]] = row["zone_id"]

    outcome_by_key = {}  # (zone_id, date, parcel_id) -> "delivered" | "failed"
    for row in scan_rows:
        zone_id = zone_by_parcel.get(row["parcel_id"])
        if zone_id is None:
            continue
        day = row["scanned_at"][:10]
        key = (zone_id, day, row["parcel_id"])
        if row["scan_type"] == "delivered":
            outcome_by_key[key] = "delivered"
        else:
            outcome_by_key.setdefault(key, "failed")

    counts_by_zone_date = {}
    for (zone_id, day, _parcel_id), outcome in outcome_by_key.items():
        bucket = counts_by_zone_date.setdefault((zone_id, day), {"delivered": 0, "failed": 0})
        bucket[outcome] += 1

    all_pairs_hold = True
    checked_pairs = 0
    for (zone_id, day), bucket in counts_by_zone_date.items():
        independently_attempted = bucket["delivered"] + bucket["failed"]
        live = m1_delivery.get_zone_performance(connection, zone_id, day)
        checked_pairs += 1
        if (
            live["n_attempted"] != independently_attempted
            or live["n_delivered"] != bucket["delivered"]
            or live["n_failed"] != bucket["failed"]
        ):
            all_pairs_hold = False

    check(
        f"D3 invariant (attempted = delivered + failed) holds for all {checked_pairs} (zone, date) pairs",
        all_pairs_hold and checked_pairs > 0,
    )


# ---------------------------------------------------------------------------
# Constraint audit: no INSERT/UPDATE/DELETE against the five input tables
# outside scripts/seed.py (decision D10.5)
# ---------------------------------------------------------------------------

FORBIDDEN_TABLES = ["parcels", "scans", "riders", "zones", "deposits"]
CRUD_PATTERN = re.compile(
    r"\b(insert\s+into|update|delete\s+from)\s+(" + "|".join(FORBIDDEN_TABLES) + r")\b",
    re.IGNORECASE,
)
EXCLUDED_DIR_NAMES = {".venv", "__pycache__", ".git"}
# scripts/seed.py is the one-time offline data hand-off (decision D10.5).
# tests/test_formulas.py builds its own throwaway in-memory SQLite database
# for unit testing (never touches cpdas.db) -- a second, independent, and
# equally legitimate exception to the "never write" rule, since it isn't
# part of the running application either.
EXCLUDED_FILES = {PROJECT_ROOT / "scripts" / "seed.py", PROJECT_ROOT / "tests" / "test_formulas.py"}


def find_crud_violations():
    violations = []
    for path in sorted(PROJECT_ROOT.rglob("*.py")):
        if any(part in EXCLUDED_DIR_NAMES for part in path.parts):
            continue
        if path in EXCLUDED_FILES:
            continue
        text = path.read_text(encoding="utf-8")
        collapsed = re.sub(r"\s+", " ", text)
        for match in CRUD_PATTERN.finditer(collapsed):
            violations.append((str(path.relative_to(PROJECT_ROOT)), match.group(0)))
    return violations


def run_constraint_audit():
    violations = find_crud_violations()
    detail = "; ".join(f"{path}: {snippet!r}" for path, snippet in violations)
    check(
        "Constraint audit: no INSERT/UPDATE/DELETE on parcels/scans/riders/zones/deposits "
        "outside scripts/seed.py and tests/test_formulas.py's own throwaway in-memory database",
        len(violations) == 0,
        detail,
    )


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

def main():
    connection = get_connection()
    try:
        run_m1_checks(connection)
        run_r2_checks(connection)
        run_m2_checks(connection)
        run_m3_checks(connection)
        run_m4_checks(connection)
        run_d3_invariant_check(connection)
    finally:
        connection.close()

    run_constraint_audit()

    print()
    print(f"{'STATUS':<6} DESCRIPTION")
    print("-" * 78)
    failed_count = 0
    for description, passed, detail in RESULTS:
        status = "PASS" if passed else "FAIL"
        if not passed:
            failed_count += 1
        print(f"{status:<6} {description}")
        if not passed and detail:
            print(f"       -> {detail}")

    print("-" * 78)
    print(f"{len(RESULTS) - failed_count} / {len(RESULTS)} checks passed")

    if failed_count > 0:
        sys.exit(1)


if __name__ == "__main__":
    main()
