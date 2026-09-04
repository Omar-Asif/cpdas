# CPDAS — Project Context

Courier and Parcel Delivery Analytics System: a read-only analytics and reporting web app for a
courier company's operations manager. CSC 470 university software-engineering lab project.

**Read `BUILD_PROMPT.md` first.** It is the full, binding specification for this project — data
model, module formulas, phase-by-phase build order, and every resolved ambiguity from the faculty
PDF. This file only adds pointers and reminders on top of it.

## The one rule that overrides everything else

**No add, update, or delete on the five input datasets**: `parcels`, `scans`, `riders`, `zones`,
`deposits`. The Flask app (`app.py`, `db.py`, everything in `modules/`) only ever runs `SELECT`
against them. The only write path in the whole running application is `INSERT INTO
zone_assignments` (append-only, computed output — see decision D2 in `docs/SPEC_DECISIONS.md`).
Those five tables are populated exactly once, offline, before the server starts, by
`scripts/seed.py` reading CSVs from `scripts/generate_data.py` — see decision D10.5.

Before touching any route or module function, check: does this write to one of the five input
tables? If yes, it's out of scope for this project, full stop — even if a user asks for it.

`scripts/verify.py` greps the codebase for `INSERT`/`UPDATE`/`DELETE` against those five table
names outside `scripts/seed.py` and fails the build if it finds one. Don't try to make that check
pass by renaming things — fix the actual violation.

## Where the ambiguity resolutions live

The faculty PDF (`spec/CSC470_Project13_Courier_Analytics_2.pdf`) is internally inconsistent in
several places (a formula disagreeing with its own prose, a totals row that doesn't add up, a week
label that doesn't match its own dates, etc.). Every one of those is resolved in
`docs/SPEC_DECISIONS.md` (decisions D1–D10, D10.5). If you're implementing a formula or a report
and the PDF seems to contradict itself, check that document before guessing — the resolution is
already decided and is graded on its own merits at the viva.

## Stack constraints (do not add dependencies)

Python 3.12+, Flask, Jinja2, and the standard-library `sqlite3` module only. `requirements.txt` is
exactly one line: `Flask==3.1.*`. No ORM, no Django, no Node/npm/React/build step, no pandas/numpy/
scikit-learn, no CSS framework. Plain SQL strings, plain `<script>`-free-by-default HTML/CSS, plain
`for` loops over comprehensions in anything that computes a spec formula.

## Explainability is graded

The student is examined individually and may be asked to explain any line, or to make a small live
change (e.g. "make this button red") during the viva. Because of that:

- No clever one-liners or metaprogramming. Prefer an explicit loop over a nested comprehension.
- Every module function has a docstring naming the PDF equation number it implements (e.g. "Eq. (1)").
- Every SQL query implementing a spec formula carries a comment naming that equation.
- All theme colours live in `static/css/theme.css` as CSS custom properties — nowhere else. That's
  intentional: it's the designated "change a colour live" surface for the viva.

## Module → file map

| Module | File | Formulas |
|---|---|---|
| M1 Delivery Performance | `modules/m1_delivery.py` | Eq. (1)–(4) |
| M2 Rider Productivity | `modules/m2_rider.py` | Eq. (5)–(6) |
| M3 COD Reconciliation | `modules/m3_cod.py` | Eq. (7)–(9) |
| M4 AI Zone Matching | `modules/m4_matching.py` | Eq. (10), cosine similarity |
| M5 Reporting | `modules/m5_reports.py` | assembles R1–R5 from M1–M4, no computation of its own |

`README.md` has the full equation-number → file/function mapping table once it exists (Phase 7).

## Build order

The project is built in 8 phases (0–7), committing after each one — see `BUILD_PROMPT.md` §11 for
the full table. If you're picking up mid-project, check `git log` to see which phases are done, and
check this repo's current file layout against `BUILD_PROMPT.md` §9 to see what's still missing.

## Verification

`scripts/verify.py` asserts every examined figure from the PDF (and the D6/D8 documented
discrepancies) against the seeded database and prints a pass/fail table. `tests/test_formulas.py`
unit-tests each formula function directly against hand-built inputs, independent of the seeded
database. Run both after any change to a module's formula logic. If a verification fails, fix the
generator or the module — never relax the assertion to make it pass.
