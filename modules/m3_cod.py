"""M3 -- COD Reconciliation.

Implements Eq. (7)-(9) and the monthly escalation flag. Every function here
only reads parcels, scans, riders and deposits -- see docs/SPEC_DECISIONS.md,
decision D10.5.
"""


# Individual COD amounts are stored to 2 decimal places, so summing several
# of them can drift by a paisa or two due to plain floating-point rounding
# (this is a storage-precision artefact, not a real shortage or over-deposit
# -- and currency displays to the nearest whole taka anyway, per decision
# D10, so anything under 1 taka is invisible on screen regardless).
RECONCILED_EPSILON = 0.5
ESCALATION_SHORTAGE_RATE_THRESHOLD_PCT = 0.5


def _get_collected(connection, rider_id, on_date):
    """C_r (Eq. 7): sum of cod_amount over parcels rider_id delivered on
    on_date."""
    query = """
        SELECT COALESCE(SUM(p.cod_amount), 0) AS collected
        FROM scans s
        JOIN parcels p ON p.parcel_id = s.parcel_id
        WHERE s.rider_id = ? AND s.scan_type = 'delivered' AND date(s.scanned_at) = ?
    """
    return connection.execute(query, (rider_id, on_date)).fetchone()["collected"]


def _get_deposited(connection, rider_id, on_date):
    """G_r: cash rider_id actually deposited on on_date, 0 if no deposit row."""
    row = connection.execute(
        "SELECT amount FROM deposits WHERE rider_id = ? AND deposit_date = ?", (rider_id, on_date)
    ).fetchone()
    return row["amount"] if row else 0.0


def get_rider_cod_reconciliation(connection, rider_id, on_date):
    """C_r, G_r, delta_r (Eq. 8) and a status label for one rider on
    on_date."""
    rider = connection.execute("SELECT rider_id, name FROM riders WHERE rider_id = ?", (rider_id,)).fetchone()
    collected = _get_collected(connection, rider_id, on_date)
    deposited = _get_deposited(connection, rider_id, on_date)
    delta = collected - deposited  # Eq. (8)

    if abs(delta) < RECONCILED_EPSILON:
        status = "Reconciled"
    elif delta > 0:
        status = "Shortage — accounts notified"
    else:
        status = "Over-deposit"  # delta < 0: usually a counting error (Section 5.2)

    return {
        "rider_id": rider["rider_id"],
        "name": rider["name"],
        "date": on_date,
        "collected": collected,
        "deposited": deposited,
        "delta": delta,
        "status": status,
    }


def get_all_cod_reconciliation(connection, on_date):
    """get_rider_cod_reconciliation for every rider on on_date, in rider_id
    order. R4 (the Daily COD Reconciliation Report) filters this down to
    riders with C_r > 0 -- that filtering is a report-display concern, done
    in modules/m5_reports.py, not here."""
    rider_ids = [row["rider_id"] for row in connection.execute("SELECT rider_id FROM riders ORDER BY rider_id")]
    return [get_rider_cod_reconciliation(connection, rider_id, on_date) for rider_id in rider_ids]


def get_monthly_shortage_rate(connection, rider_id, month):
    """Eq. (9): ShortageRate_r over every day in month ('YYYY-MM') that
    rider_id collected any COD, plus the escalation flag (Section 5.3:
    escalated to the accounts manager when ShortageRate_r exceeds 0.5% over
    the month)."""
    query = """
        SELECT DISTINCT date(s.scanned_at) AS delivery_date
        FROM scans s
        WHERE s.rider_id = ? AND s.scan_type = 'delivered' AND strftime('%Y-%m', s.scanned_at) = ?
    """
    delivery_dates = [row["delivery_date"] for row in connection.execute(query, (rider_id, month)).fetchall()]

    total_collected = 0.0
    total_shortage = 0.0
    for delivery_date in delivery_dates:
        collected = _get_collected(connection, rider_id, delivery_date)
        deposited = _get_deposited(connection, rider_id, delivery_date)
        delta = collected - deposited  # Eq. (8)
        total_collected += collected
        total_shortage += max(0.0, delta)  # Eq. (9): over-deposits do not offset shortages

    shortage_rate_pct = (total_shortage / total_collected * 100) if total_collected else 0.0
    escalation_flag = shortage_rate_pct > ESCALATION_SHORTAGE_RATE_THRESHOLD_PCT

    return shortage_rate_pct, escalation_flag
