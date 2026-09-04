# CPDAS — Courier and Parcel Delivery Analytics System

A read-only analytics and reporting web application for the operations manager of
**Dhrutogoti Courier**, a courier company in Dhaka. CPDAS reads five datasets that other,
out-of-scope systems (booking counters, the riders' handheld scanner app, the cash office) already
capture — parcels, scans, riders, zones and deposits — and computes delivery performance, rider
productivity, COD reconciliation, AI-based address-to-zone matching, and five printable operations
reports. It never adds, updates, or deletes a row in any of those five datasets; see
[Hard constraints](#hard-constraints) below.

Built for CSC 470: Software Engineering Lab, Project 13. The full specification is in
[`spec/CSC470_Project13_Courier_Analytics_2.pdf`](spec/CSC470_Project13_Courier_Analytics_2.pdf);
[`BUILD_PROMPT.md`](BUILD_PROMPT.md) is the binding build specification that resolves every
ambiguity in it.

## Hard constraints

- **No add, update, or delete operations** on `parcels`, `scans`, `riders`, `zones`, or `deposits`.
  The Flask app only ever runs `SELECT` against them.
- The one exception is `zone_assignments`, an append-only table that stores M4's computed output
  (never business data). It is `INSERT`-only — see decision D2 in
  [`docs/SPEC_DECISIONS.md`](docs/SPEC_DECISIONS.md).
- Those five tables are populated exactly once, offline, before the server starts, by
  `scripts/seed.py` — not by the running application. See decision D10.5.

## Setup

### Windows

```bash
setup.bat
```

Then run the app:

```bash
.venv\Scripts\activate.bat && python app.py
```

### macOS / Linux

```bash
./setup.sh
```

Then run the app:

```bash
source .venv/bin/activate && python app.py
```

Either script creates a virtual environment, installs the one dependency (`Flask==3.1.*`), generates
the deterministic seed CSVs into `data/`, and builds `cpdas.db` from them. Once the server is
running, open `http://127.0.0.1:5000/`.

## Regenerating the database

The CSVs in `data/` are committed to the repository, so a teammate can rebuild an identical
database without regenerating anything:

```bash
python scripts/seed.py
```

To regenerate the CSVs themselves from scratch (deterministic — the RNG is seeded with a fixed
constant, so this always produces the same output) and then rebuild the database from them:

```bash
python scripts/generate_data.py
python scripts/seed.py
```

`cpdas.db` is gitignored on purpose — a binary database file in git produces unmergeable conflicts
between teammates. Rebuild it locally with the commands above.

## Running the verification suite

```bash
python scripts/verify.py
```

Asserts every examined figure from the faculty specification against the seeded database, using the
same module functions the running application calls, and audits the codebase for any
`INSERT`/`UPDATE`/`DELETE` against the five input tables outside `scripts/seed.py`. Prints a
pass/fail table and exits non-zero if anything fails.

Unit tests for each formula, built against small hand-written inputs independent of the seeded
database, run with:

```bash
python -m unittest tests.test_formulas -v
```

## Equation-to-implementation map

| Equation | Formula | File | Function |
|---|---|---|---|
| Eq. (1) | `Success_z = n_del_z / n_att_z * 100` | [`modules/m1_delivery.py`](modules/m1_delivery.py) | `get_zone_performance` |
| Eq. (2) | `T_p = t_del_p - t_book_p` | [`modules/m1_delivery.py`](modules/m1_delivery.py) | `_resolve_daily_outcomes` |
| Eq. (3) | `OnTime_z = \|{p : T_p <= P_p}\| / n_del_z * 100` | [`modules/m1_delivery.py`](modules/m1_delivery.py) | `get_zone_performance` |
| Eq. (4) | `T_bar_z = (1/n_del_z) * sum(T_p)` | [`modules/m1_delivery.py`](modules/m1_delivery.py) | `get_zone_performance`, `get_weekly_zone_performance` |
| Eq. (5) | `pi_r = n_del_r / d_r` | [`modules/m2_rider.py`](modules/m2_rider.py) | `get_rider_productivity` |
| Eq. (6) | `FailRate_r = n_fail_r / (n_del_r + n_fail_r) * 100` | [`modules/m2_rider.py`](modules/m2_rider.py) | `get_rider_productivity` |
| Eq. (7) | `C_r = sum(m_p for p in delivered(r))` | [`modules/m3_cod.py`](modules/m3_cod.py) | `_get_collected` |
| Eq. (8) | `delta_r = C_r - G_r` | [`modules/m3_cod.py`](modules/m3_cod.py) | `get_rider_cod_reconciliation` |
| Eq. (9) | `ShortageRate_r = sum(max(0,delta_r)) / sum(C_r) * 100` | [`modules/m3_cod.py`](modules/m3_cod.py) | `get_monthly_shortage_rate` |
| Eq. (10) | `sim(A,C) = (A . C) / (\|\|A\|\| * \|\|C\|\|)` | [`modules/text_similarity.py`](modules/text_similarity.py) | `binary_cosine_similarity` |
| Eq. (10) upgrade | TF-IDF: `w_t = tf_t * log(N/df_t)` | [`modules/m4_matching.py`](modules/m4_matching.py) | `_tfidf_scores`, `_tfidf_vector`, `_tfidf_cosine_similarity` |

Supporting computations not tied to a single equation number:

| Computation | File | Function |
|---|---|---|
| D3 per-parcel-per-date outcome resolution | [`modules/m1_delivery.py`](modules/m1_delivery.py) | `_resolve_daily_outcomes` |
| Operations-review flag (3 consecutive days < 85%) | [`modules/m1_delivery.py`](modules/m1_delivery.py) | `_operations_review_flag`, `_find_flag_streak_start` |
| D1 secondary hub-out-to-delivery metric | [`modules/m1_delivery.py`](modules/m1_delivery.py) | `_average_hub_out_to_delivery_hours` |
| D5 company average productivity + coaching flag | [`modules/m2_rider.py`](modules/m2_rider.py) | `get_all_rider_productivity` |
| Auto-assign resolution (threshold + tie-to-manual-queue) | [`modules/m4_matching.py`](modules/m4_matching.py) | `resolve_auto_assignment` |
| Dispatcher override (D2 append-only) | [`modules/m4_matching.py`](modules/m4_matching.py) | `record_manual_override` |
| R1-R5 assembly (no computation, calls M1-M4) | [`modules/m5_reports.py`](modules/m5_reports.py) | `get_r1_report` … `get_r5_report` |
| Display rounding (round-half-up, decision D10) | [`modules/formatting.py`](modules/formatting.py) | `round_half_up` and the `format_*` functions |

## Known specification discrepancies

The faculty PDF contains several internal contradictions (a formula that disagrees with its own
prose, a totals row that doesn't add up, a week label that doesn't match its own dates, and more).
Every one of them is resolved, with reasoning, in [`docs/SPEC_DECISIONS.md`](docs/SPEC_DECISIONS.md)
— decisions D1 through D10, plus D10.5. Where this project's behaviour differs from a literal
reading of the PDF, that document explains why.

## Print support

`static/css/print.css` sizes reports for A4 and hides the sidebar, top bar and buttons when
printing. It includes an `@page` margin-box rule for a page number, but browser support for that
CSS feature varies — the print dialog's own header/footer option is the reliable fallback if page
numbers don't appear.

## Repository layout

```
cpdas/
├── app.py                    # Flask app, routes only — no computation
├── db.py                     # connection helper
├── schema.sql
├── requirements.txt
├── setup.bat / setup.sh
├── docs/SPEC_DECISIONS.md    # D1-D10.5 with reasoning
├── data/                     # generated CSVs (committed)
├── scripts/
│   ├── generate_data.py      # deterministic seed-data generator
│   ├── seed.py                # builds cpdas.db from schema.sql + data/
│   └── verify.py              # asserts every examined figure + CRUD audit
├── modules/                  # M1-M5 + shared helpers, all computation lives here
├── templates/                # base.html, partials/, forms/, reports/
├── static/                   # css/theme.css (all colours), app.css, print.css, js/theme.js
└── tests/test_formulas.py    # unit tests, independent of the seeded database
```
