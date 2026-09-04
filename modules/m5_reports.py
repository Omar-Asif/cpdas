"""M5 -- Reporting.

Assembles the data each printable report (R1-R5) needs by calling M1-M4.
No formula or computation is implemented in this file -- see modules/
m1_delivery.py, m2_rider.py, m3_cod.py and m4_matching.py for those.

Built up one report per build phase: R1 here in phase 3, R3/R4/R5 added in
their own phases, R2 added last in phase 7 alongside scripts/verify.py.
"""

from modules import m1_delivery, m2_rider, m3_cod, m4_matching


def _zone_name_lookup(connection):
    rows = connection.execute("SELECT zone_id, zone_name FROM zones").fetchall()
    return {row["zone_id"]: row["zone_name"] for row in rows}


def get_r2_report(connection, end_date):
    """Assemble R2: Zone Performance Report (Section 7.2 of the PDF).

    Per decision D7, this is the 7-day window ending on end_date, inclusive
    -- not a specific ISO week number, which the PDF's own "Week 27, 2026"
    label contradicts against its own quoted dates. The recommendation line
    names the first flagged zone, if any; the PDF only ever shows one.
    """
    zone_names = _zone_name_lookup(connection)
    zone_rows = m1_delivery.get_all_weekly_zone_performance(connection, end_date)
    for zone_row in zone_rows:
        zone_row["zone_name"] = zone_names[zone_row["zone_id"]]

    recommendation = None
    for zone_row in zone_rows:
        if zone_row["flag_day_index"] is not None:
            recommendation = f"One additional rider for {zone_row['zone_name']}."
            break

    return {
        "end_date": end_date,
        "start_date": zone_rows[0]["start_date"] if zone_rows else end_date,
        "iso_week": zone_rows[0]["iso_week"] if zone_rows else None,
        "zones": zone_rows,
        "recommendation": recommendation,
    }


def get_r1_report(connection, on_date):
    """Assemble R1: Daily Delivery Report (Section 7.1 of the PDF).

    Per-zone figures come straight from m1_delivery.get_all_zone_performance.
    The totals row is a plain sum/re-derivation of those same per-zone
    numbers (decision D6: the per-zone figures are authoritative, so the
    totals row is computed honestly from them rather than forced to match
    the PDF's own internally-inconsistent totals line).
    """
    zone_names = _zone_name_lookup(connection)
    zone_rows = m1_delivery.get_all_zone_performance(connection, on_date)
    for zone_row in zone_rows:
        zone_row["zone_name"] = zone_names[zone_row["zone_id"]]

    total_attempted = sum(z["n_attempted"] for z in zone_rows)
    total_delivered = sum(z["n_delivered"] for z in zone_rows)
    total_failed = sum(z["n_failed"] for z in zone_rows)
    total_on_time = sum(z["on_time_count"] for z in zone_rows)

    total_success_pct = (total_delivered / total_attempted * 100) if total_attempted else 0.0  # Eq. (1)
    total_on_time_pct = (total_on_time / total_delivered * 100) if total_delivered else 0.0    # Eq. (3)

    top_reason, top_reason_count, top_reason_total_failed = m1_delivery.get_top_failure_reason(connection, on_date)

    return {
        "date": on_date,
        "zones": zone_rows,
        "totals": {
            "n_attempted": total_attempted,
            "n_delivered": total_delivered,
            "n_failed": total_failed,
            "success_pct": total_success_pct,
            "on_time_pct": total_on_time_pct,
        },
        "top_failure_reason": top_reason,
        "top_failure_reason_count": top_reason_count,
        "top_failure_reason_total_failed": top_reason_total_failed,
    }


def get_r3_report(connection, month):
    """Assemble R3: Rider Productivity Report (Section 7.3 of the PDF).

    Per-rider figures and the company average/threshold come straight from
    m2_rider.get_all_rider_productivity. The only thing added here is the
    "Note" text each row shows -- a purely presentational label derived
    from the coaching_flag / above_average booleans that module already
    computed, not a new calculation.
    """
    rider_rows, mean_productivity, coaching_threshold = m2_rider.get_all_rider_productivity(connection, month)

    for row in rider_rows:
        if row["coaching_flag"]:
            row["note"] = "Coaching list"
        elif row["above_average"]:
            row["note"] = "Above average"
        else:
            row["note"] = ""

    return {
        "month": month,
        "riders": rider_rows,
        "mean_productivity": mean_productivity,
        "coaching_threshold": coaching_threshold,
    }


def get_r4_report(connection, on_date):
    """Assemble R4: Daily COD Reconciliation Report (Section 7.4 of the PDF).

    Filters modules.m3_cod.get_all_cod_reconciliation down to riders with
    C_r > 0, per BUILD_PROMPT.md's design constraint for this report --
    everyone else was prepaid-only that day and has nothing to reconcile.
    """
    all_rows = m3_cod.get_all_cod_reconciliation(connection, on_date)
    cod_rows = [row for row in all_rows if row["collected"] > 0]

    total_collected = sum(row["collected"] for row in cod_rows)
    total_deposited = sum(row["deposited"] for row in cod_rows)
    total_shortage = sum(max(0.0, row["delta"]) for row in cod_rows)  # Eq. (9) numerator, for the day
    # Use the status m3_cod already computed (which tolerates the same
    # paisa-level float drift as the "Reconciled" label) rather than a raw
    # delta > 0 check, so a rider whose delta is a rounding artefact isn't
    # miscounted as having a real shortage.
    riders_with_shortage = sum(1 for row in cod_rows if row["status"].startswith("Shortage"))

    return {
        "date": on_date,
        "riders": cod_rows,
        "totals": {
            "collected": total_collected,
            "deposited": total_deposited,
            "shortage": total_shortage,
            "riders_with_shortage": riders_with_shortage,
        },
    }


def get_r5_report(connection, on_date):
    """Assemble R5: AI Zone Assignment Log (Section 7.5 of the PDF).

    Everything comes straight from m4_matching.get_zone_assignment_log --
    per decision D8, R5's summary counts here are illustrative rather than
    pinned to the PDF's exact sample figures.
    """
    return m4_matching.get_zone_assignment_log(connection, on_date)
