"""M1 -- Delivery Performance Analytics.

Implements Eq. (1)-(4) from the faculty specification, the operations-review
flag, and the decision-D1 secondary "hub-out to delivery" metric. Every
function here only reads parcels/scans/zone_assignments -- see
docs/SPEC_DECISIONS.md, decision D10.5.

A parcel's zone is always its most recent zone_assignments row (decision D2):
the row with the highest id for that parcel_id. A parcel's outcome on a given
date is resolved to exactly one of "delivered" or "failed" (decision D3):
delivered wins if both a delivered and a failed_attempt scan exist for that
parcel on that date; a parcel with neither is excluded entirely from that
date's figures (it is still in transit).
"""

from datetime import datetime, timedelta

ZONE_IDS = ["Z-MIR", "Z-UTT", "Z-DHN"]

OPERATIONS_REVIEW_THRESHOLD_PCT = 85.0
OPERATIONS_REVIEW_CONSECUTIVE_DAYS = 3


def _resolve_daily_outcomes(connection, zone_id, on_date):
    """Resolve every parcel currently assigned to zone_id to exactly one
    outcome for on_date (decision D3).

    Returns a dict keyed by parcel_id, each value a dict with "outcome"
    ("delivered" or "failed"), "delivery_hours" (Eq. 2's T_p, only set when
    delivered), and "promised_hours".
    """
    query = """
        -- Source rows for Eq. (1)-(4): delivered/failed_attempt scans on the
        -- selected date, restricted to parcels currently assigned to this
        -- zone (decision D2: current zone = highest-id zone_assignments row).
        SELECT s.parcel_id, s.scan_type, s.scanned_at, p.booked_at, p.promised_hours
        FROM scans s
        JOIN parcels p ON p.parcel_id = s.parcel_id
        JOIN zone_assignments za ON za.parcel_id = s.parcel_id
        WHERE za.zone_id = ?
          AND za.id = (SELECT MAX(id) FROM zone_assignments WHERE parcel_id = s.parcel_id)
          AND s.scan_type IN ('delivered', 'failed_attempt')
          AND date(s.scanned_at) = ?
    """
    rows = connection.execute(query, (zone_id, on_date)).fetchall()

    outcomes = {}
    for row in rows:
        parcel_id = row["parcel_id"]
        if parcel_id not in outcomes:
            # Default to failed; a delivered scan for this parcel (seen on
            # any row, in any order) always overrides this below.
            outcomes[parcel_id] = {
                "outcome": "failed",
                "delivery_hours": None,
                "promised_hours": row["promised_hours"],
            }
        if row["scan_type"] == "delivered":
            booked_at = datetime.strptime(row["booked_at"], "%Y-%m-%d %H:%M:%S")
            delivered_at = datetime.strptime(row["scanned_at"], "%Y-%m-%d %H:%M:%S")
            delivery_hours = (delivered_at - booked_at).total_seconds() / 3600  # Eq. (2)
            outcomes[parcel_id]["outcome"] = "delivered"
            outcomes[parcel_id]["delivery_hours"] = delivery_hours

    return outcomes


def _average_hub_out_to_delivery_hours(connection, zone_id, on_date):
    """Decision D1 secondary metric: average hours from the hub_out scan to
    the delivered scan, for delivered parcels in zone_id on on_date. This is
    Section 3.1's prose reading of the PDF; it is display-only and never
    feeds Eq. (3), the operations-review flag, or any report.
    """
    query = """
        SELECT hub_out.scanned_at AS hub_out_at, delivered.scanned_at AS delivered_at
        FROM scans delivered
        JOIN scans hub_out ON hub_out.parcel_id = delivered.parcel_id AND hub_out.scan_type = 'hub_out'
        JOIN zone_assignments za ON za.parcel_id = delivered.parcel_id
        WHERE delivered.scan_type = 'delivered'
          AND za.zone_id = ?
          AND za.id = (SELECT MAX(id) FROM zone_assignments WHERE parcel_id = delivered.parcel_id)
          AND date(delivered.scanned_at) = ?
    """
    rows = connection.execute(query, (zone_id, on_date)).fetchall()
    if not rows:
        return 0.0

    total_hours = 0.0
    for row in rows:
        hub_out_at = datetime.strptime(row["hub_out_at"], "%Y-%m-%d %H:%M:%S")
        delivered_at = datetime.strptime(row["delivered_at"], "%Y-%m-%d %H:%M:%S")
        total_hours += (delivered_at - hub_out_at).total_seconds() / 3600
    return total_hours / len(rows)


def _operations_review_flag(connection, zone_id, on_date):
    """True if Success_z (Eq. 1) was below 85% on each of the 3 consecutive
    days ending on on_date (Section 3.3 of the PDF: "A zone whose success
    rate stays below 85% for three consecutive days is flagged for an
    operations review")."""
    selected_date = datetime.strptime(on_date, "%Y-%m-%d").date()

    for days_back in range(OPERATIONS_REVIEW_CONSECUTIVE_DAYS):
        day = selected_date - timedelta(days=days_back)
        outcomes = _resolve_daily_outcomes(connection, zone_id, day.isoformat())
        n_attempted = len(outcomes)
        if n_attempted == 0:
            return False
        n_delivered = sum(1 for o in outcomes.values() if o["outcome"] == "delivered")
        success_pct = n_delivered / n_attempted * 100  # Eq. (1)
        if success_pct >= OPERATIONS_REVIEW_THRESHOLD_PCT:
            return False

    return True


def get_zone_performance(connection, zone_id, on_date):
    """Full M1 figures for one zone on one date: Eq. (1)-(4), decision D1's
    secondary metric, and the operations-review flag.

    on_date is a string 'YYYY-MM-DD'. Returns a dict of unrounded values --
    round only at render time (decision D10)."""
    outcomes = _resolve_daily_outcomes(connection, zone_id, on_date)

    n_delivered = 0
    n_failed = 0
    on_time_count = 0
    delivery_time_sum = 0.0

    for info in outcomes.values():
        if info["outcome"] == "delivered":
            n_delivered += 1
            delivery_time_sum += info["delivery_hours"]
            if info["delivery_hours"] <= info["promised_hours"]:
                on_time_count += 1
        else:
            n_failed += 1

    n_attempted = n_delivered + n_failed  # decision D3

    success_pct = (n_delivered / n_attempted * 100) if n_attempted else 0.0       # Eq. (1)
    on_time_pct = (on_time_count / n_delivered * 100) if n_delivered else 0.0     # Eq. (3)
    avg_delivery_hours = (delivery_time_sum / n_delivered) if n_delivered else 0.0  # Eq. (4)

    return {
        "zone_id": zone_id,
        "date": on_date,
        "n_attempted": n_attempted,
        "n_delivered": n_delivered,
        "n_failed": n_failed,
        "success_pct": success_pct,
        "on_time_count": on_time_count,
        "on_time_pct": on_time_pct,
        "avg_delivery_hours": avg_delivery_hours,
        "avg_hub_out_to_delivery_hours": _average_hub_out_to_delivery_hours(connection, zone_id, on_date),
        "operations_review_flag": _operations_review_flag(connection, zone_id, on_date),
    }


def get_all_zone_performance(connection, on_date):
    """get_zone_performance for every zone, in zone catalogue order --
    used by R1 (the Daily Delivery Report)."""
    return [get_zone_performance(connection, zone_id, on_date) for zone_id in ZONE_IDS]


def _find_flag_streak_start(daily_success_pct):
    """First 1-based day index (within the list) starting a run of 3
    consecutive days below 85% success, or None if no such run exists.
    A day with no attempted parcels (None in the list) cannot be part of a
    streak, matching _operations_review_flag's same "no data = no flag"
    rule for a single date.
    """
    for start_index in range(len(daily_success_pct) - OPERATIONS_REVIEW_CONSECUTIVE_DAYS + 1):
        window = daily_success_pct[start_index:start_index + OPERATIONS_REVIEW_CONSECUTIVE_DAYS]
        if all(pct is not None and pct < OPERATIONS_REVIEW_THRESHOLD_PCT for pct in window):
            return start_index + 1
    return None


def get_weekly_zone_performance(connection, zone_id, end_date):
    """R2 (Zone Performance Report): the 7-day window ending on end_date,
    inclusive (decision D7). Success_z (Eq. 1) and T_bar_z (Eq. 4) are
    aggregated over the whole window's totals, the same way R1's totals row
    aggregates a single day's per-zone figures (decision D6) -- not an
    average of each day's own percentage.
    """
    end = datetime.strptime(end_date, "%Y-%m-%d").date()
    start = end - timedelta(days=6)
    window_dates = [(start + timedelta(days=offset)).isoformat() for offset in range(7)]

    total_attempted = 0
    total_delivered = 0
    total_delivery_time = 0.0
    daily_success_pct = []

    for day in window_dates:
        outcomes = _resolve_daily_outcomes(connection, zone_id, day)
        day_delivered = 0
        day_attempted = len(outcomes)
        day_delivery_time = 0.0
        for info in outcomes.values():
            if info["outcome"] == "delivered":
                day_delivered += 1
                day_delivery_time += info["delivery_hours"]

        total_attempted += day_attempted
        total_delivered += day_delivered
        total_delivery_time += day_delivery_time
        daily_success_pct.append((day_delivered / day_attempted * 100) if day_attempted else None)

    success_pct = (total_delivered / total_attempted * 100) if total_attempted else 0.0    # Eq. (1)
    avg_delivery_hours = (total_delivery_time / total_delivered) if total_delivered else 0.0  # Eq. (4)

    return {
        "zone_id": zone_id,
        "start_date": start.isoformat(),
        "end_date": end_date,
        "iso_week": end.isocalendar()[1],
        "volume": total_attempted,
        "success_pct": success_pct,
        "avg_delivery_hours": avg_delivery_hours,
        "flag_day_index": _find_flag_streak_start(daily_success_pct),
    }


def get_all_weekly_zone_performance(connection, end_date):
    """get_weekly_zone_performance for every zone -- used by R2."""
    return [get_weekly_zone_performance(connection, zone_id, end_date) for zone_id in ZONE_IDS]


def get_top_failure_reason(connection, on_date):
    """Most common failure_reason among distinct parcels that resolved to
    'failed' (decision D3) on on_date, city-wide across all zones -- used by
    R1's "Top failure reason today" line.

    If a parcel failed more than once that day (decision D4), its most
    recent attempt's reason is the one counted, since that is the reason
    the parcel most recently failed for.

    Returns (reason_text, count_for_that_reason, total_failed_parcels), or
    (None, 0, 0) if nothing failed that day.
    """
    delivered_query = """
        SELECT DISTINCT parcel_id FROM scans
        WHERE scan_type = 'delivered' AND date(scanned_at) = ?
    """
    delivered_parcel_ids = {
        row["parcel_id"] for row in connection.execute(delivered_query, (on_date,)).fetchall()
    }

    failed_attempts_query = """
        SELECT parcel_id, failure_reason, scanned_at
        FROM scans
        WHERE scan_type = 'failed_attempt' AND date(scanned_at) = ?
        ORDER BY scanned_at
    """
    rows = connection.execute(failed_attempts_query, (on_date,)).fetchall()

    latest_reason_by_parcel = {}
    for row in rows:
        parcel_id = row["parcel_id"]
        if parcel_id in delivered_parcel_ids:
            continue  # decision D3: this parcel resolved to delivered that day
        # Rows are ordered by scanned_at, so the last write for a parcel_id
        # here is always its most recent attempt that day.
        latest_reason_by_parcel[parcel_id] = row["failure_reason"]

    if not latest_reason_by_parcel:
        return None, 0, 0

    reason_counts = {}
    for reason in latest_reason_by_parcel.values():
        reason_counts[reason] = reason_counts.get(reason, 0) + 1

    top_reason = max(reason_counts, key=lambda reason: reason_counts[reason])
    return top_reason, reason_counts[top_reason], len(latest_reason_by_parcel)
