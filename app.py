"""CPDAS Flask application.

Routes only -- no computation lives here. Every route either renders a
template directly or calls into modules/m1_delivery.py .. m5_reports.py for
the numbers, then hands the result to a template. Every database access this
file (directly or through the modules it calls) ever performs against the
five input tables (parcels, scans, riders, zones, deposits) is a SELECT; see
docs/SPEC_DECISIONS.md, decision D10.5.
"""

from flask import Flask, render_template

app = Flask(__name__)


@app.route("/")
def index():
    """Landing page: links to the five modules."""
    return render_template("index.html")


# ---------------------------------------------------------------------------
# Module placeholder routes. Each of these is replaced with real content in
# its own build phase (see BUILD_PROMPT.md Section 11) -- M1 in phase 3, M2
# in phase 4, M3 in phase 5, M4 in phase 6, M5 in phase 7.
# ---------------------------------------------------------------------------

@app.route("/m1")
def m1_page():
    return render_template(
        "placeholder.html", module_id="M1", module_name="Delivery Performance Analytics",
        module_purpose="Delivery success rate, on-time percentage and average delivery time per zone.",
        active_module="m1",
    )


@app.route("/m2")
def m2_page():
    return render_template(
        "placeholder.html", module_id="M2", module_name="Rider Productivity Analytics",
        module_purpose="Parcels delivered per rider per duty day, and each rider's failed-attempt rate.",
        active_module="m2",
    )


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
    return render_template(
        "placeholder.html", module_id="M5", module_name="Reporting",
        module_purpose="Printable operations reports R1-R5.",
        active_module="m5",
    )


if __name__ == "__main__":
    app.run(debug=True)
