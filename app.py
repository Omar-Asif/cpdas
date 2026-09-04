"""CPDAS Flask application.

Routes only -- no computation lives here. Every route either renders a
template directly or calls into modules/m1_delivery.py .. m5_reports.py for
the numbers, then hands the result to a template. Every database access this
file (directly or through the modules it calls) ever performs against the
five input tables (parcels, scans, riders, zones, deposits) is a SELECT; see
docs/SPEC_DECISIONS.md, decision D10.5.
"""

from flask import Flask, redirect, render_template, request, url_for

from db import get_connection
from modules import formatting, m1_delivery, m2_rider, m3_cod, m4_matching, m5_reports

app = Flask(__name__)

# Every report/form value is rounded only for display (decision D10); these
# filters are how templates do that rounding, consistently, in one place.
app.jinja_env.filters["number"] = formatting.format_number
app.jinja_env.filters["percent"] = formatting.format_percent
app.jinja_env.filters["hours"] = formatting.format_hours
app.jinja_env.filters["similarity_percent"] = formatting.format_similarity_percent
app.jinja_env.filters["currency"] = formatting.format_currency
app.jinja_env.filters["date_long"] = formatting.format_date_long
app.jinja_env.filters["month_long"] = formatting.format_month_long

DEFAULT_DATE = "2026-07-08"  # the most recent date the seed data covers
DEFAULT_MONTH = "2026-06"    # the month the M2 worked examples use


@app.route("/")
def index():
    """Landing page: links to the five modules."""
    return render_template("index.html")


# ---------------------------------------------------------------------------
# M1 -- Delivery Performance Analytics
# ---------------------------------------------------------------------------

@app.route("/m1")
def m1_page():
    """Zone Performance Enquiry Form (Section 3.4 of the PDF)."""
    zone_id = request.args.get("zone", "Z-MIR")
    on_date = request.args.get("date", DEFAULT_DATE)

    connection = get_connection()
    try:
        zones = connection.execute("SELECT zone_id, zone_name FROM zones ORDER BY zone_id").fetchall()
        result = m1_delivery.get_zone_performance(connection, zone_id, on_date)
    finally:
        connection.close()

    return render_template(
        "forms/m1_enquiry.html", zones=zones, selected_zone=zone_id, selected_date=on_date,
        result=result, active_module="m1",
    )


@app.route("/reports/r1")
def r1_report():
    """R1: Daily Delivery Report (Section 7.1 of the PDF)."""
    on_date = request.args.get("date", DEFAULT_DATE)

    connection = get_connection()
    try:
        report = m5_reports.get_r1_report(connection, on_date)
    finally:
        connection.close()

    return render_template("reports/r1.html", report=report, active_module="m5")


@app.route("/m2")
def m2_page():
    """Rider productivity enquiry: all riders for a month, plus a
    per-rider failure-reason breakdown (Section 4.2 of the PDF)."""
    month = request.args.get("month", DEFAULT_MONTH)
    detail_rider_id = request.args.get("rider")

    connection = get_connection()
    try:
        rider_rows, mean_productivity, coaching_threshold = m2_rider.get_all_rider_productivity(connection, month)
        if detail_rider_id is None and rider_rows:
            detail_rider_id = rider_rows[0]["rider_id"]
        reason_breakdown = (
            m2_rider.get_failure_reason_breakdown(connection, detail_rider_id, month)
            if detail_rider_id else []
        )
    finally:
        connection.close()

    return render_template(
        "forms/m2_enquiry.html", riders=rider_rows, mean_productivity=mean_productivity,
        coaching_threshold=coaching_threshold, selected_month=month, detail_rider_id=detail_rider_id,
        reason_breakdown=reason_breakdown, active_module="m2",
    )


@app.route("/reports/r3")
def r3_report():
    """R3: Rider Productivity Report (Section 7.3 of the PDF)."""
    month = request.args.get("month", DEFAULT_MONTH)

    connection = get_connection()
    try:
        report = m5_reports.get_r3_report(connection, month)
    finally:
        connection.close()

    return render_template("reports/r3.html", report=report, active_module="m5")


@app.route("/m3")
def m3_page():
    """COD Reconciliation enquiry: all riders for a date, plus a per-rider
    monthly ShortageRate_r drill-down (Eq. 9)."""
    on_date = request.args.get("date", DEFAULT_DATE)
    detail_rider_id = request.args.get("rider")
    detail_month = request.args.get("month", on_date[:7])

    connection = get_connection()
    try:
        rider_rows = m3_cod.get_all_cod_reconciliation(connection, on_date)
        if detail_rider_id is None and rider_rows:
            detail_rider_id = rider_rows[0]["rider_id"]
        shortage_rate_pct, escalation_flag = (
            m3_cod.get_monthly_shortage_rate(connection, detail_rider_id, detail_month)
            if detail_rider_id else (0.0, False)
        )
    finally:
        connection.close()

    return render_template(
        "forms/m3_enquiry.html", riders=rider_rows, selected_date=on_date, detail_rider_id=detail_rider_id,
        detail_month=detail_month, shortage_rate_pct=shortage_rate_pct, escalation_flag=escalation_flag,
        active_module="m3",
    )


@app.route("/reports/r4")
def r4_report():
    """R4: Daily COD Reconciliation Report (Section 7.4 of the PDF)."""
    on_date = request.args.get("date", DEFAULT_DATE)

    connection = get_connection()
    try:
        report = m5_reports.get_r4_report(connection, on_date)
    finally:
        connection.close()

    return render_template("reports/r4.html", report=report, active_module="m5")


@app.route("/m4")
def m4_page():
    """Address Matching Form (Section 6.4 of the PDF).

    A GET here never writes anything: ranked_scores is a pure preview
    computed fresh every load. Only the "Run AI Matching" and "Override"
    actions below (both POST) ever INSERT into zone_assignments.
    """
    parcel_id = request.args.get("parcel", "PC-77012")
    use_tfidf = request.args.get("tfidf") == "1"

    connection = get_connection()
    try:
        parcel = connection.execute(
            "SELECT parcel_id, delivery_address FROM parcels WHERE parcel_id = ?", (parcel_id,)
        ).fetchone()
        ranked_scores = (
            m4_matching.score_parcel_against_zones(connection, parcel["delivery_address"], use_tfidf)
            if parcel else []
        )
        preview_zone_id, _ = m4_matching.resolve_auto_assignment(ranked_scores)
        current_assignment = m4_matching.get_current_assignment(connection, parcel_id) if parcel else None
        zones = connection.execute("SELECT zone_id, zone_name FROM zones ORDER BY zone_id").fetchall()
        unmatched_parcels = m4_matching.get_unmatched_parcels(connection)
    finally:
        connection.close()

    return render_template(
        "forms/m4_enquiry.html", parcel=parcel, parcel_id=parcel_id, use_tfidf=use_tfidf,
        ranked_scores=ranked_scores, preview_zone_id=preview_zone_id, current_assignment=current_assignment,
        zones=zones, unmatched_parcels=unmatched_parcels, active_module="m4",
    )


@app.route("/m4/run", methods=["POST"])
def m4_run_matching():
    """Run AI Matching: score the parcel and INSERT one 'auto'
    zone_assignments row (decision D2 -- append-only)."""
    parcel_id = request.form["parcel_id"]
    use_tfidf = request.form.get("tfidf") == "1"

    connection = get_connection()
    try:
        m4_matching.record_auto_assignment(connection, parcel_id, use_tfidf)
    finally:
        connection.close()

    return redirect(url_for("m4_page", parcel=parcel_id, tfidf="1" if use_tfidf else "0"))


@app.route("/m4/override", methods=["POST"])
def m4_override():
    """Dispatcher override: INSERT a 'manual' zone_assignments row choosing
    the dispatcher's zone, regardless of similarity score (Section 6.1)."""
    parcel_id = request.form["parcel_id"]
    chosen_zone_id = request.form["zone_id"]

    connection = get_connection()
    try:
        m4_matching.record_manual_override(connection, parcel_id, chosen_zone_id)
    finally:
        connection.close()

    return redirect(url_for("m4_page", parcel=parcel_id))


@app.route("/m4/batch", methods=["POST"])
def m4_batch_matching():
    """Batch-assign every parcel with no zone_assignments row yet."""
    use_tfidf = request.form.get("tfidf") == "1"

    connection = get_connection()
    try:
        summary = m4_matching.run_batch_matching(connection, use_tfidf)
    finally:
        connection.close()

    return render_template("forms/m4_batch_result.html", summary=summary, active_module="m4")


@app.route("/reports/r5")
def r5_report():
    """R5: AI Zone Assignment Log (Section 7.5 of the PDF)."""
    on_date = request.args.get("date", DEFAULT_DATE)

    connection = get_connection()
    try:
        report = m5_reports.get_r5_report(connection, on_date)
    finally:
        connection.close()

    return render_template("reports/r5.html", report=report, active_module="m5")


@app.route("/m5")
def m5_page():
    return render_template("reports/index.html", active_module="m5")


if __name__ == "__main__":
    app.run(debug=True)
