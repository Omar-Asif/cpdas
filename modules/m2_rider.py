"""M2 -- Rider Productivity Analytics.

Implements Eq. (5)-(6), the company average productivity per decision D5,
the coaching flag, and the per-reason failure breakdown. Every function here
only reads riders and scans -- see docs/SPEC_DECISIONS.md, decision D10.5.

Note on `riders.duty_days`: the schema stores exactly one duty-day count per
rider (Section 1 of the PDF: "duty days in the period"), not one per month.
The seed data sets it to each rider's June 2026 duty days, matching the
Section 4.3 worked example. If the month selector below is pointed at a
different month, `pi_r` is still divided by that same stored figure, since
no per-month attendance data exists in the given schema -- this is a
limitation of the data model as specified, not a bug in this module.

"""

COACHING_FAIL_RATE_THRESHOLD_PCT = 15.0
COACHING_PRODUCTIVITY_FACTOR = 0.7  # decision D5: coaching if pi_r < 0.7 * pi_bar


def _count_scans(connection, rider_id, scan_type, month):
    query = """
        SELECT COUNT(*) AS n
        FROM scans
        WHERE rider_id = ? AND scan_type = ? AND strftime('%Y-%m', scanned_at) = ?
    """
    row = connection.execute(query, (rider_id, scan_type, month)).fetchone()
    return row["n"]


def get_rider_productivity(connection, rider_id, month):
    """pi_r (Eq. 5) and FailRate_r (Eq. 6) for one rider in one month
    ('YYYY-MM'). Does not include the coaching flag or company average --
    those need every rider's figures at once, see get_all_rider_productivity.
    """
    rider = connection.execute(
        "SELECT rider_id, name, home_zone, duty_days FROM riders WHERE rider_id = ?", (rider_id,)
    ).fetchone()

    n_delivered = _count_scans(connection, rider_id, "delivered", month)
    # decision D4: M2's failed count is failed-attempt SCAN ROWS, not
    # distinct parcels -- a parcel that failed 3 times contributes 3 here
    # (contrast with M1's n_fail_z, which counts distinct failed parcels).
    n_failed = _count_scans(connection, rider_id, "failed_attempt", month)

    duty_days = rider["duty_days"]
    pi_r = (n_delivered / duty_days) if duty_days else 0.0                                # Eq. (5)
    n_attempts = n_delivered + n_failed
    fail_rate_pct = (n_failed / n_attempts * 100) if n_attempts else 0.0                   # Eq. (6)

    return {
        "rider_id": rider["rider_id"],
        "name": rider["name"],
        "home_zone": rider["home_zone"],
        "duty_days": duty_days,
        "month": month,
        "n_delivered": n_delivered,
        "n_failed": n_failed,
        "pi_r": pi_r,
        "fail_rate_pct": fail_rate_pct,
    }


def get_all_rider_productivity(connection, month):
    """Every rider's productivity for month, plus the company average and
    coaching threshold (decision D5), with each rider's coaching_flag and
    above_average flag filled in.

    Returns (rider_rows, mean_productivity, coaching_threshold) -- all
    unrounded; round only at render time (decision D10).
    """
    rider_ids = [row["rider_id"] for row in connection.execute("SELECT rider_id FROM riders ORDER BY rider_id")]
    rider_rows = [get_rider_productivity(connection, rider_id, month) for rider_id in rider_ids]

    # decision D5: pi_bar is the arithmetic mean of the riders' own pi_r
    # values, not total delivered / total duty days.
    mean_productivity = sum(row["pi_r"] for row in rider_rows) / len(rider_rows) if rider_rows else 0.0
    coaching_threshold = COACHING_PRODUCTIVITY_FACTOR * mean_productivity

    for row in rider_rows:
        # Both comparisons use unrounded values (decision D10) -- comparing
        # against the *displayed* rounded threshold could put a rider on the
        # wrong side of a borderline case.
        row["coaching_flag"] = (row["pi_r"] < coaching_threshold) or (row["fail_rate_pct"] > COACHING_FAIL_RATE_THRESHOLD_PCT)
        row["above_average"] = row["pi_r"] > mean_productivity

    return rider_rows, mean_productivity, coaching_threshold


def get_failure_reason_breakdown(connection, rider_id, month):
    """Count of each failure_reason text among rider_id's failed_attempt
    scans in month (Section 4.2: "so the manager can see why deliveries
    fail"), most common first."""
    query = """
        SELECT failure_reason, COUNT(*) AS reason_count
        FROM scans
        WHERE rider_id = ? AND scan_type = 'failed_attempt' AND strftime('%Y-%m', scanned_at) = ?
        GROUP BY failure_reason
        ORDER BY reason_count DESC
    """
    rows = connection.execute(query, (rider_id, month)).fetchall()
    return [{"reason": row["failure_reason"], "count": row["reason_count"]} for row in rows]
