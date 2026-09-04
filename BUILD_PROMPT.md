# CPDAS — Master Build Prompt

You are building a complete, working project. Read this entire file before writing any code, then
build it phase by phase in the order given at the end. Commit after every phase.

---

## 1. What you are building

**Courier and Parcel Delivery Analytics System (CPDAS)** — a read-only analytics and reporting web
application for the operations manager of "Dhrutogoti Courier", a courier company in Dhaka.
This is a university software-engineering lab project (CSC 470). The faculty specification PDF is in
the repo root as `spec/CSC470_Project13_Courier_Analytics_2.pdf` — read it. This file resolves
every ambiguity in it. **Where this file and the PDF disagree, this file wins.**

The system reads five stored datasets and computes analytics over them. It has five modules:

| ID | Module | Purpose |
|----|--------|---------|
| M1 | Delivery Performance Analytics | Success rate, on-time %, average delivery time per zone |
| M2 | Rider Productivity Analytics | Parcels/duty-day per rider, failed-attempt rate |
| M3 | COD Reconciliation | Cash collected vs deposited per rider per day, shortages |
| M4 | AI Address-to-Zone Matching | Cosine-similarity matching of free-text addresses to zones |
| M5 | Reporting | Five printable A4 reports (R1–R5) |

---

## 2. Hard constraints — do not violate these

1. **No add, delete, or update operations on the five input datasets.** This is the single most
   important rule in the specification. The application must contain no form, route, or function
   that inserts, updates, or deletes rows in `parcels`, `scans`, `riders`, `zones`, or `deposits`.
   Open those tables read-only from the Flask app. All marks are for computation, matching and
   reporting.
2. **The only exception** is the append-only `zone_assignments` table (see M4). It stores computed
   output, never business data. It is INSERT-only — never UPDATE, never DELETE.
3. **Stack is fixed**: Python 3.12+, Flask, Jinja2, and Python's built-in `sqlite3` module.
   - **No Django. No SQLAlchemy or any ORM. No Node.js, npm, React, or build step. No pandas,
     numpy, or scikit-learn. No CSS framework (no Bootstrap/Tailwind).**
   - `requirements.txt` contains exactly one line: `Flask==3.1.*`
   - Write plain SQL strings against `sqlite3`. Every SQL query implementing a specification
     formula must carry a comment naming the equation, e.g. `# Eq. (1): Success_z = n_del / n_att * 100`.
4. **Explainability is a graded requirement.** The student will be examined individually and asked
   to explain arbitrary lines of this code and to make live changes (e.g. "change this button to
   red"). Therefore: no clever one-liners, no metaprogramming, no deep abstraction layers. Prefer
   an explicit `for` loop over a nested comprehension. Prefer a named intermediate variable over a
   chained expression. Short functions with docstrings that name the equation they implement.
5. **Cross-platform.** Developed on Windows, run by teammates on Windows and macOS. Use `pathlib`,
   never hardcode path separators. No OS-specific calls.

---

## 3. Settled specification ambiguities

The faculty PDF contains internal contradictions. These are the binding resolutions. **Implement
each one exactly as stated, and record all of them in `docs/SPEC_DECISIONS.md`** with the reasoning
— that document is itself worth marks and will be used in the viva.

### D1 — Delivery time is measured from booking, not hub-out
Section 3.1 prose says "average time from hub-out to delivery", but Eq. (2) says
`T_p = t_del_p − t_book_p`. The worked example (33.0 h against a 48 h promise) matches Eq. (2).

**Implement Eq. (2): booking timestamp → delivered-scan timestamp, in hours.**
Additionally compute and display a clearly labelled secondary metric "Avg. hub-out to delivery"
on the M1 screen only, so both readings are available if questioned. All flags, reports and
on-time calculations use Eq. (2).

### D2 — Dispatcher override without violating the no-update rule
Section 6.1 requires recording assignments and allowing dispatcher reassignment; Section 8 forbids
update operations.

**Resolution:** zone assignment is never stored on the `parcels` row. It lives in an append-only
`zone_assignments` table `(id, parcel_id, zone_id, similarity_score, source, created_at)` where
`source` is `'auto'` or `'manual'`. A dispatcher override INSERTs a new row; the previous row is
never modified or deleted. A parcel's current zone is derived at query time as the row with the
highest `id` for that `parcel_id`. This gives a full audit trail, which §6.1 explicitly requires.

### D3 — Definition of "attempted"
Report R1 in the PDF satisfies `attempted = delivered + failed` for every zone
(250 = 228+22, 198 = 186+12, 174 = 148+26).

**Resolution:** for each `(parcel, date)` pair, resolve to exactly one outcome:
- **delivered** if any `delivered` scan exists for that parcel on that date;
- else **failed** if any `failed attempt` scan exists on that date;
- else the parcel is in transit and is **excluded entirely** from that date's figures.

`n_att = n_del + n_fail`. Parcels with only a `hub out` scan never enter the denominator.

### D4 — M1 counts parcels, M2 counts attempts
This distinction is deliberate and must be implemented correctly, or R1 and R3 will contradict
each other.

- **M1 (`n_fail_z`)** counts **distinct parcels** whose resolved outcome on the date was failed.
- **M2 (`n_fail_r`)** counts **failed-attempt scan rows** recorded by that rider (Eq. 6's worked
  example: 508 + 52 = 560 *attempts*).

One parcel that failed three times contributes **1** to M1 and **3** to M2. Write this in a code
comment at both call sites.

### D5 — Company average productivity
Section 4.2 says π̄ is "computed over all riders" without specifying the method.

**Resolution:** π̄ is the **arithmetic mean of the individual rider productivities**
(`sum(π_r for each rider) / rider_count`), not total-delivered ÷ total-duty-days. The coaching
threshold is `0.7 × π̄`, compared against **unrounded** values, displayed rounded to 1 decimal
(0.7 × 19.5 = 13.65, displayed as 13.7 — exactly as the PDF's R3 footer shows).

### D6 — R1 totals row rounding discrepancy
The PDF's R1 totals row states an on-time rate of 89.5%, but the per-zone on-time counts implied by
its own percentages (205 + 172 + 125 = 502 of 562) give 89.3%. The PDF is internally inconsistent
by one parcel.

**Resolution:** the **per-zone figures are authoritative** — those appear in the M1 worked example
and on the enquiry form, and are what an examiner will check. Compute the totals row honestly from
the actual data (it will read 89.3%). Note the discrepancy in `docs/SPEC_DECISIONS.md`.

### D7 — Weekly report period
The PDF labels R2 "Week 27, 2026", but ISO week 27 of 2026 is 29 June – 5 July, which does not
contain 8 July, whose figures R2 quotes.

**Resolution:** R2 takes an **end date** and reports the **7-day window ending on that date**
(inclusive). Label it with the explicit date range and the ISO week number of the end date, e.g.
"7-day period: 02 July – 08 July 2026 (ISO week 28)". This sidesteps the week-numbering ambiguity
entirely.

### D8 — M4 secondary percentages are illustrative
The §6.3 worked example (PC-77012 scoring exactly 80% against Z-MIR) is fully specified and
**must reproduce exactly**. The other figures scattered through §6.3/§6.4/R5 (16%, 91%, 42%) are
not mutually satisfiable with any single consistent zone-description vocabulary — 16% requires the
Uttara description to hold 8 distinct terms, while 91% requires roughly 3.

**Resolution:** guarantee the 80% case exactly, and author the Uttara description with **8 distinct
cleaned terms sharing exactly one term with PC-77012's address**, which yields 15.8% → displays as
16%. Treat the remaining sample percentages as illustrative and let them fall out of the real data.
Note this in `docs/SPEC_DECISIONS.md`.

### D9 — Deposits are a fifth input dataset
§1 lists four datasets but §5.2 requires `G_r`, the cash a rider actually deposited. §1's prose
does say the cash office records "collections and deposits".

**Resolution:** add a fifth read-only input dataset `deposits (rider_id, deposit_date, amount)`.
Document it as derived from §1's cash-office sentence.

### D10.5 — How data enters the system without violating the no-CRUD rule
§1 frames all five datasets as already captured by other, out-of-scope systems: "booking counters
already record every parcel", "the riders' handheld app already records every scan", "the cash
office already records cash-on-delivery (COD) collections and deposits." CPDAS's stated purpose is
only to "analyse the stored data" — it is explicitly not the system that captures it.

**Resolution:** the Flask application never writes to the five input tables — only reads them. The
one and only population of those tables happens **offline, once, before the web server starts**,
via `scripts/seed.py` loading CSVs from `scripts/generate_data.py`. This is not a feature of the
graded application; it plays the role of the one-time data hand-off from the three upstream systems
the spec presupposes already exist (booking counters, rider handheld app, cash office) — the same
role a CSV import or ETL job would play against a real courier company's existing systems. It never
runs while the app is serving requests, and it is explicitly excluded from the CRUD audit in
`scripts/verify.py` (§10) for exactly this reason.

### D10 — Display precision
- Percentages in M1, M2, M3 and reports R1–R4: **1 decimal place**.
- Hours: **1 decimal place**.
- Similarity percentages in M4 and R5: **integer** (the PDF shows 80%, 91%, 42%, 16%).
- Currency: BDT, thousands separators, no decimals.
- **Always compute at full precision and round only at render time.** Threshold comparisons
  (85%, 15%, 0.5%, 0.80 similarity, `0.7 × π̄`) use unrounded values.
- The similarity threshold is `>= 0.80` (the worked example lands on exactly 0.80 and is
  auto-assigned).

---

## 4. Data model

Create `schema.sql` with these tables. Fixed schema, no migrations.

```sql
CREATE TABLE zones (
    zone_id      TEXT PRIMARY KEY,      -- 'Z-MIR'
    zone_name    TEXT NOT NULL,         -- 'Mirpur'
    hub          TEXT NOT NULL,         -- 'Mirpur hub'
    description  TEXT NOT NULL          -- free text: areas, landmarks, spelling variants
);

CREATE TABLE riders (
    rider_id     TEXT PRIMARY KEY,      -- 'RD-114'
    name         TEXT NOT NULL,
    home_zone    TEXT NOT NULL REFERENCES zones(zone_id),
    duty_days    INTEGER NOT NULL       -- duty days in the reporting period
);

CREATE TABLE parcels (
    parcel_id        TEXT PRIMARY KEY,  -- 'PC-77012'
    booked_at        TEXT NOT NULL,     -- ISO 8601 'YYYY-MM-DD HH:MM:SS'
    promised_hours   INTEGER NOT NULL,  -- e.g. 48
    delivery_address TEXT NOT NULL,     -- free text
    cod_amount       REAL NOT NULL      -- 0 for prepaid
);

CREATE TABLE scans (
    scan_id     INTEGER PRIMARY KEY,
    parcel_id   TEXT NOT NULL REFERENCES parcels(parcel_id),
    scan_type   TEXT NOT NULL CHECK (scan_type IN ('hub_out','delivered','failed_attempt')),
    rider_id    TEXT NOT NULL REFERENCES riders(rider_id),
    scanned_at  TEXT NOT NULL,
    failure_reason TEXT                 -- NULL unless scan_type = 'failed_attempt'
);

CREATE TABLE deposits (
    rider_id     TEXT NOT NULL REFERENCES riders(rider_id),
    deposit_date TEXT NOT NULL,         -- 'YYYY-MM-DD'
    amount       REAL NOT NULL,
    PRIMARY KEY (rider_id, deposit_date)
);

-- Computed output only. INSERT-only. See decision D2.
CREATE TABLE zone_assignments (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    parcel_id        TEXT NOT NULL REFERENCES parcels(parcel_id),
    zone_id          TEXT REFERENCES zones(zone_id),   -- NULL = manual sorting queue
    similarity_score REAL NOT NULL,
    source           TEXT NOT NULL CHECK (source IN ('auto','manual')),
    created_at       TEXT NOT NULL
);
```

Add indexes on `scans(parcel_id)`, `scans(rider_id)`, `scans(scanned_at)`,
`zone_assignments(parcel_id)`.

**Note the deliberate absence of `parcels.assigned_zone`.** The PDF mentions such a column, but
storing it there would force UPDATE operations. Decision D2 replaces it. Explain this in
`SPEC_DECISIONS.md`.

---

## 5. Seed data — must reproduce the specification's worked examples

Write `scripts/generate_data.py` that deterministically generates CSVs into `data/`
(**seed the RNG with a fixed constant so output is reproducible**), and `scripts/seed.py` that
creates the SQLite database from `schema.sql` and loads those CSVs.

The generated data **must** reproduce these examined figures exactly.

### Zones (exactly 3)
| zone_id | name | Description must clean to |
|---|---|---|
| Z-MIR | Mirpur | exactly `{mirpur, pallabi, kazipara, shewrapara, section}` — 5 terms |
| Z-UTT | Uttara | exactly 8 distinct terms, sharing exactly **one** term with PC-77012's cleaned address (use `school`) |
| Z-DHN | Dhanmondi | 5–8 terms, sharing **none** with PC-77012's address |

Verify the cleaned term sets programmatically after writing the descriptions — do not assume.

### M1 targets — 08 July 2026
| Zone | Attempted | Delivered | Failed | On-time count | Sum of delivery times |
|---|---|---|---|---|---|
| Z-MIR | 250 | 228 | 22 | 205 | 7,524.0 h |
| Z-UTT | 198 | 186 | 12 | 172 | — |
| Z-DHN | 174 | 148 | 26 | 125 | — |

Z-MIR must yield Success 91.2%, On-time 89.9%, average 33.0 h.

**Technique for hitting the exact time sum:** generate 227 delivery durations by drawing from a
plausible distribution, then set the 228th as `7524.0 − sum(first 227)`, clamping the draw range so
the residual lands within a realistic bound (e.g. 4–90 h). Retry the draw if it doesn't. Do the
same for the on-time counts: choose exactly 205 parcels to have `T_p <= promised_hours` and 23 to
exceed it. Promised hours should vary across parcels (24, 48, 72) to make the on-time logic
non-trivial.

### M1 operations-review flag
`Z-DHN` must sit **below 85% success on three consecutive days** within the 7-day window ending
08 July 2026, but **not** on 08 July itself (where R1 shows 85.1%). Place the streak on 04–06 July.
`Z-MIR` on 08 July must show flag = No.

### R2 targets — 7-day window ending 08 July 2026
| Zone | Avg delivery time | 7-day success | Volume |
|---|---|---|---|
| Z-UTT | 29.4 h | 94.1% | 1,310 |
| Z-MIR | 33.0 h | 90.8% | 1,702 |
| Z-DHN | 41.6 h | 83.9% | 1,166 |

### M2 targets — June 2026
| Rider | Name | Delivered | Duty days | π_r | Failed attempts | FailRate |
|---|---|---|---|---|---|---|
| RD-114 | Sumon Mia | 508 | 24 | 21.2 | 52 | 9.3% |
| RD-108 | Alamgir Hossain | 472 | 25 | 18.9 | 61 | 11.4% |
| RD-131 | Liton Sarker | 296 | 23 | 12.9 | 64 | 17.8% |

RD-114's failure reasons must break down as: 31 "customer unreachable", 14 "address not found",
7 other reasons.

Generate **additional riders (aim for 8 total)** whose productivities are tuned so that the
arithmetic mean π̄ across all riders **rounds to 19.5**, making the coaching threshold
`0.7 × 19.5 = 13.65` display as 13.7 and placing RD-131 (12.9) on the coaching list while RD-114
and RD-108 stay off it. Solve for the extra riders' figures numerically in the generator — do not
hand-guess.

### M3 targets — 08 July 2026
| Rider | Collected C_r | Deposited G_r | Δ_r |
|---|---|---|---|
| RD-114 | 38,450 | 38,450 | 0 |
| RD-108 | 31,220 | 31,220 | 0 |
| RD-131 | 27,300 | 26,300 | 1,000 |

Totals: collected 96,970, deposited 95,970, shortage 1,000 from one rider.

**Design constraint that makes this clean:** on 08 July 2026, only these three riders deliver
parcels carrying a non-zero COD amount. Every other rider delivers prepaid parcels only
(`cod_amount = 0`) that day. R4 filters to riders with `C_r > 0`, so it renders exactly the three
rows in the PDF and the totals match. The COD amounts of each rider's delivered parcels must sum
to the exact figures above — use the same residual technique as the delivery times.

### M4 targets
Parcel `PC-77012` must exist with the address exactly:
`House 12, Road 3, Section 7, Pallabi, Mirpur, opposite Kazipara school`
It must clean to `{section, pallabi, mirpur, kazipara, school}` (5 terms) and score exactly
`4 / (sqrt(5) * sqrt(5)) = 0.80` against Z-MIR → auto-assigned, displayed as 80%.

Provide **at least 15 hand-authored demonstration addresses across the three zones** in
`data/demo_addresses.csv`, covering: clean matches, spelling variants ("Mirpur"/"Mirpore"),
landmark-only addresses, and at least two that fall below threshold into the manual queue
(including `near college gate, Dhaka`). These are for the §8.4 demonstration requirement.

### Volume
Roughly 4,500–5,000 parcels spanning June and the first week of July 2026, so both the monthly M2
window and the weekly R2 window have real data. Keep generation under ~30 seconds.

---

## 6. Module implementations

Each module is one file in `modules/`, exposing plain functions that take a `sqlite3.Connection`
plus parameters and return dictionaries or lists of dictionaries. No classes unless genuinely
warranted. Every function's docstring names the equation it implements.

### M1 — `modules/m1_delivery.py`
```
Success_z  = n_del_z / n_att_z * 100                       # Eq. (1)
T_p        = t_del_p - t_book_p        (hours)             # Eq. (2)
OnTime_z   = |{p : T_p <= P_p}| / n_del_z * 100            # Eq. (3)   NOTE: denominator is n_del
T_bar_z    = (1 / n_del_z) * sum(T_p)                      # Eq. (4)
```
Plus: operations-review flag = success below 85% on three consecutive days ending on the selected
date. Plus the D1 secondary hub-out-to-delivery average.

### M2 — `modules/m2_rider.py`
```
pi_r       = n_del_r / d_r                                 # Eq. (5)
FailRate_r = n_fail_r / (n_del_r + n_fail_r) * 100         # Eq. (6)
```
Plus: π̄ per D5, coaching flag (`π_r < 0.7 * π̄` **or** `FailRate_r > 15`), and a per-reason count
of failure texts.

### M3 — `modules/m3_cod.py`
```
C_r          = sum(m_p for p in parcels delivered by r that day)   # Eq. (7)
delta_r      = C_r - G_r                                            # Eq. (8)
ShortageRate = sum(max(0, delta_r)) / sum(C_r) * 100                # Eq. (9)
```
Note Eq. (9) uses `max(0, Δ)` so over-deposits do **not** offset shortages. Escalation flag when
`ShortageRate > 0.5` over a month.

### M4 — `modules/m4_matching.py`
```
sim(A, C) = (A · C) / (||A|| * ||C||)                      # Eq. (10)
```

**Tokenisation pipeline — implement in this exact order** (reverse-engineered from the §6.3 worked
example, which requires "school" to survive and "opposite" and all bare numbers to be removed):

1. lowercase
2. strip punctuation, split on whitespace
3. drop pure numbers (`12`, `3`, `7`)
4. drop generic address words: `house, road, flat, floor`
5. drop positional stop-words: `opposite, near, beside, behind, front, of, the, at, in, side`
6. deduplicate into a set

Binary term vectors: `A · C` = count of common terms; `||A||` = sqrt(count of distinct terms).

**Binary mode is the default.** TF–IDF (`w_t = tf_t * log(N / df_t)`, N = number of zone
descriptions) is a **toggle** on the matching form, off by default, presented as the bonus-credit
upgrade. This ordering matters: TF–IDF does not reproduce the examined 80% figure, so binary must
be what loads by default.

Ties: if two zones score equal and both `>= 0.80`, send the parcel to the manual queue rather than
picking arbitrarily. Document this.

Functions: score one parcel against all zones (returning a ranked list), run a batch assignment
over all unassigned parcels, and record a dispatcher override — all writing to `zone_assignments`
by INSERT only.

### M5 — `modules/m5_reports.py`
Assembles data for R1–R5 by calling M1–M4. No computation logic duplicated here.

---

## 7. Reports R1–R5

All render as HTML pages that print cleanly to A4. Each carries the company header
("Dhrutogoti Courier"), report title, report date/period, and a page number.

| ID | Report | Parameters |
|----|--------|-----------|
| R1 | Daily Delivery Report | date → per-zone attempted/delivered/failed/success/on-time + totals + top failure reason |
| R2 | Zone Performance Report | end date → 7-day window per D7: avg delivery time, 7-day success, volume, flag, recommendation line |
| R3 | Rider Productivity Report | month → per rider delivered/duty days/π_r/FailRate/note + π̄ and threshold footer |
| R4 | Daily COD Reconciliation | date → per rider collected/deposited/Δ/status + totals (filtered to C_r > 0) |
| R5 | AI Zone Assignment Log | date → parcel, address prefix, assigned zone, similarity %, status + summary counts |

Match the PDF's column layouts and footer summary lines in §7.1–§7.5.

---

## 8. User interface

### Look and feel
Modelled on the Claude web app's visual language, applied to Dhrutogoti Courier branding.
**Do not use Anthropic's logo, the name "Claude", or any Anthropic brand mark anywhere.**

- Left sidebar with the five module links; top bar with company name and the theme toggle.
- Flat surfaces, no gradients, no drop shadows, hairline borders, generous whitespace.
- Rounded cards (12px), system sans-serif stack.
- Accent colour used sparingly — primary action buttons only.

### Theme system — this is the graded "live edit" surface
Define **every colour** as a CSS custom property in a single `static/css/theme.css`, under
`:root[data-theme="light"]` and `:root[data-theme="dark"]`. No colour literal may appear anywhere
else in any CSS or template file.

```css
:root[data-theme="dark"] {
  --bg: #1f1e1c;  --surface: #2a2926;  --border: #3d3b37;
  --text: #ece8e1; --text-muted: #a39d92; --accent: #d97757;
}
:root[data-theme="light"] {
  --bg: #faf9f5;  --surface: #ffffff;   --border: #e5e1d8;
  --text: #2b2a28; --text-muted: #77726a; --accent: #c1602f;
}
```

`static/js/theme.js` toggles `data-theme` on `<html>` and persists the choice in `localStorage`.
Set the attribute in an inline script in `<head>` before first paint to avoid a flash.

Because `base.html` is the only place these are defined, changing any colour across the whole
application is a one-line edit. This is deliberate — the examiner may ask for exactly that.

### Forms
Two input forms are named explicitly in the PDF and must match its field lists:
- **Zone Performance Enquiry Form** (§3.4): zone dropdown, date, Compute, Print Report; outputs for
  success rate, on-time rate, average delivery time, operations review flag.
- **Address Matching Form** (§6.4): parcel ID, read-only address text, Run AI Matching, TF–IDF
  toggle; outputs for assigned zone with score, second-best zone with score, dispatcher override.

Build equivalent enquiry forms for M2 (month selector) and M3 (date selector).

### Print
`static/css/print.css` under `@media print`: `@page { size: A4; margin: 15mm; }`, hide sidebar,
top bar, and all buttons, force light colours regardless of active theme, avoid page breaks inside
table rows, repeat table headers across pages via `thead { display: table-header-group; }`.
Include an `@page` margin-box page-number rule; note in the README that browser support varies and
the print dialog's own header/footer option is the reliable fallback.

---

## 9. Repository layout

```
cpdas/
├── app.py                    # Flask app, routes only — no computation
├── db.py                     # connection helper, read-only where applicable
├── schema.sql
├── requirements.txt          # one line: Flask==3.1.*
├── setup.bat                 # Windows one-shot setup
├── setup.sh                  # macOS/Linux equivalent
├── README.md
├── CLAUDE.md                 # project context for future Claude Code sessions
├── .gitignore
├── spec/
│   └── CSC470_Project13_Courier_Analytics_2.pdf
├── docs/
│   └── SPEC_DECISIONS.md     # decisions D1–D10 with reasoning
├── data/                     # generated CSVs, committed to git
├── scripts/
│   ├── generate_data.py
│   ├── seed.py
│   └── verify.py
├── modules/
│   ├── m1_delivery.py … m5_reports.py
├── templates/
│   ├── base.html, partials/, forms/, reports/
├── static/
│   ├── css/theme.css, app.css, print.css
│   └── js/theme.js
└── tests/
    └── test_formulas.py
```

`.gitignore` must exclude `.venv/`, `__pycache__/`, `*.pyc`, and **`cpdas.db`** (a binary database
in git produces unmergeable conflicts). The CSVs in `data/` **are** committed, so any teammate
rebuilds the identical database with one command.

---

## 10. Verification — build this, do not skip it

`scripts/verify.py` runs against the seeded database and asserts every examined figure, printing a
pass/fail table. It must check at minimum:

- M1 Z-MIR on 2026-07-08: success 91.2%, on-time 89.9%, average 33.0 h, flag = No
- M1 Z-UTT: 93.9% / 92.5%; M1 Z-DHN: 85.1% / 84.5%
- R1 totals: 622 attempted, 562 delivered, 60 failed
- M2: RD-114 = 21.2 & 9.3%; RD-108 = 18.9 & 11.4%; RD-131 = 12.9 & 17.8%; π̄ = 19.5; threshold 13.7
- M2: RD-131 on the coaching list, RD-114 and RD-108 not
- M3 on 2026-07-08: the three C_r/G_r/Δ_r rows and the 96,970 / 95,970 / 1,000 totals
- M4: `PC-77012` scores exactly 0.80 against Z-MIR and is auto-assigned; second-best Z-UTT ≈ 16%
- M4: `near college gate, Dhaka` scores below 0.80 against all three zones
- D3 invariant: for every zone and date, `attempted == delivered + failed`
- Constraint audit: grep the codebase and assert no `INSERT`/`UPDATE`/`DELETE` statement targets
  `parcels`, `scans`, `riders`, `zones`, or `deposits` outside `scripts/seed.py`

`tests/test_formulas.py` unit-tests each formula function against the PDF's worked examples using
hand-built inputs, independent of the seeded database.

**If a verification fails, fix the generator or the module until it passes.** Do not relax the
assertion.

---

## 11. Build order — commit after every phase

Ordered so that if work is interrupted, the highest-weighted and most examinable pieces are already
complete and working.

| Phase | Deliverable | Commit message |
|---|---|---|
| 0 | Repo scaffold, `.gitignore`, `requirements.txt`, `setup.bat`/`setup.sh`, `CLAUDE.md`, `docs/SPEC_DECISIONS.md` with D1–D10 | `chore: project scaffold and specification decisions` |
| 1 | `schema.sql`, `db.py`, `scripts/generate_data.py`, `scripts/seed.py` — database builds and loads | `feat: database schema and deterministic seed data` |
| 2 | `base.html`, theme system, sidebar/topbar, `print.css`, Flask app skeleton with a landing page | `feat: application shell, theme toggle and print stylesheet` |
| 3 | M1 module + enquiry form + report R1 | `feat(m1): delivery performance analytics and daily report` |
| 4 | M2 module + form + report R3 | `feat(m2): rider productivity analytics and report` |
| 5 | M3 module + form + report R4 | `feat(m3): COD reconciliation and daily report` |
| 6 | M4 module + matching form + report R5 + TF–IDF toggle + 15 demo addresses | `feat(m4): AI address-to-zone matching with cosine similarity` |
| 7 | Report R2, `scripts/verify.py`, `tests/test_formulas.py`, README | `feat: weekly zone report, verification suite and documentation` |

**After each phase:** run the app, confirm the new screens render in both themes, run `verify.py`
if it exists yet, then `git add -A && git commit`. Report progress before starting the next phase.

At the very end, run `verify.py` and the test suite, and print a summary of every examined figure
with pass/fail status.

---

## 12. README requirements

`README.md` must contain: what the project is, the exact setup commands for Windows and macOS,
how to regenerate the database, how to run the verification script, a table mapping each PDF
equation number to the file and function that implements it, and a short "known specification
discrepancies" section pointing at `docs/SPEC_DECISIONS.md`.

That equation-to-function mapping table is the single most useful artefact for viva preparation —
make it complete and accurate.
