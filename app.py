"""CPDAS Flask application.

Routes only -- no computation lives here. Every route either renders a
template directly or calls into modules/m1_delivery.py .. m5_reports.py for
the numbers, then hands the result to a template. Every database access this
file (directly or through the modules it calls) ever performs against the
five input tables (parcels, scans, riders, zones, deposits) is a SELECT; see
docs/SPEC_DECISIONS.md, decision D10.5.
"""

from flask import Flask, render_template, request

from db import get_connection
from modules import formatting, m1_delivery, m2_rider, m5_reports

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
    return render_template(
        "placeholder.html", module_id="M3", module_name="COD Reconciliation",
        module_purpose="Cash collected, deposited and any shortage, per rider and per day.",
        active_module="m3",
    )


@app.route("/m4")
def m4_page():
    return render_template(
        "placeholder.html", module_id="M4", module_name="AI Address-to-Zone Matching",
        module_purpose="Cosine-similarity matching of free-text delivery addresses to delivery zones.",
        active_module="m4",
    )


@app.route("/m5")
def m5_page():
    return render_template("reports/index.html", active_module="m5")


if __name__ == "__main__":
    app.run(debug=True)
