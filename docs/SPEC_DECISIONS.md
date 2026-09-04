# Specification Decisions

The faculty specification (`spec/CSC470_Project13_Courier_Analytics_2.pdf`) contains a number of
internal contradictions and unspecified details. This document records the binding resolution for
each one, with the reasoning behind it, so that the implementation is unambiguous and defensible at
the viva. Where the PDF and this document disagree, this document wins — see `BUILD_PROMPT.md` §1.

Decisions are numbered D1–D10, plus D10.5, in the order they arise when reading the PDF
top to bottom.

---

## D1 — Delivery time is measured from booking, not hub-out

**The contradiction.** §3.1's prose describes M1 as computing "the average time from hub-out to
delivery." But Eq. (2) defines `T_p = t_del_p − t_book_p` — booking time to delivered time, not
hub-out time to delivered time. The §3.3 worked example (33.0 h average against a 48 h promise) is
only reproducible under Eq. (2): a hub-out-to-delivery reading over the same data would be smaller
and would not match.

**Resolution.** Implement Eq. (2) literally: `T_p` = delivered-scan timestamp minus booking
timestamp, in hours. This is what all on-time calculations, flags, and reports (R1–R3) use.
Because the prose reading is also a fair thing for an examiner to expect, M1's screen additionally
computes and clearly labels a secondary metric, "Avg. hub-out to delivery," so both readings are
visible without contradicting each other. That secondary metric is display-only; it never feeds
`OnTime_z`, the operations-review flag, or any report.

**Why the formula wins over the prose.** A worked numeric example is falsifiable and was checked;
prose is a paraphrase and was not. When they disagree, the formula (backed by the worked example)
is authoritative.

---

## D2 — Dispatcher override without violating the no-update rule

**The contradiction.** §6.1 says "the dispatcher can reassign any parcel," implying some field
gets changed. §8's constraint reminder and the hard constraint in `BUILD_PROMPT.md` §2 forbid any
UPDATE or DELETE against the five input datasets, which would include a `parcels.assigned_zone`
column if one existed.

**Resolution.** Zone assignment is never stored as a column on `parcels`. It lives in a separate,
append-only table:

```
zone_assignments (id, parcel_id, zone_id, similarity_score, source, created_at)
```

`source` is `'auto'` (M4's batch matching) or `'manual'` (a dispatcher override). Both cases are
plain `INSERT`s. A reassignment inserts a new row for the same `parcel_id`; the previous row is
never touched. A parcel's *current* zone is derived at query time as the row with the highest `id`
for that `parcel_id` (see `modules/m4_matching.py`).

**Why this satisfies both requirements.** §6.1 asks for reassignment capability and, implicitly,
for a trustworthy record of what happened — an audit trail is a natural reading of "the dispatcher
can reassign any parcel," and an append-only log gives a *better* audit trail than an UPDATE would
(the old assignment isn't lost). This also explains the deliberate absence of `parcels.assigned_zone`
from `schema.sql`, even though §1 lists "assigned zone (blank until assigned)" as a parcel field —
storing it there would force an UPDATE the first time a parcel got matched.

---

## D3 — Definition of "attempted"

**The ambiguity.** The PDF never defines `n_att_z` precisely. But R1's worked example is internally
consistent under one specific rule: 250 = 228 + 22 (Z-MIR), 198 = 186 + 12 (Z-UTT),
174 = 148 + 26 (Z-DHN) — i.e. `attempted = delivered + failed` exactly, with no separate
"still in transit" bucket muddying the denominator.

**Resolution.** For each `(parcel, date)` pair, resolve to exactly one outcome for that date:

1. **delivered** — if any `delivered` scan exists for that parcel on that date;
2. else **failed** — if any `failed_attempt` scan exists for that parcel on that date;
3. else the parcel is excluded entirely from that date's M1 figures (it is still in transit; a
   lone `hub_out` scan with no resolution that day is not an "attempt" for M1 purposes).

`n_att_z = n_del_z + n_fail_z` follows directly and is enforced as an invariant, checked in
`scripts/verify.py`.

**Why per-(parcel, date) rather than per-scan.** If a parcel had two `failed_attempt` scans on two
different days before eventually being delivered on a third, counting every scan row as an
"attempt" for M1 would let one parcel inflate `n_att_z` on multiple dates and break the
`delivered + failed = attempted` identity the worked example depends on. Resolving to one outcome
per parcel per day keeps M1 a per-parcel, per-date measure — consistent with D4 below, which
requires M1 to count parcels, not scan rows.

---

## D4 — M1 counts parcels, M2 counts attempts

**The distinction.** M1's `n_fail_z` (used in `Success_z`) must count **distinct parcels** whose
resolved outcome (per D3) on the date was failed. M2's `n_fail_r` (used in `FailRate_r`, Eq. 6)
counts **failed-attempt scan rows** recorded by that rider — this is required by the §4.3 worked
example, where 508 delivered + 52 failed = 560 total *attempts*, not 560 distinct parcels.

**Resolution.** Implement both counts as specified, and comment both call sites explicitly:

- `modules/m1_delivery.py`: `n_fail_z` = `COUNT(DISTINCT parcel_id)` over parcels resolved to
  `failed` that date, per D3.
- `modules/m2_rider.py`: `n_fail_r` = `COUNT(*)` over `failed_attempt` scan rows for that rider in
  the period — a parcel that fails three times before eventual delivery contributes 3 here.

**Why both are correct simultaneously.** M1 answers "how many parcels failed" (an operations
question — one parcel needing another visit is one problem, not three). M2 answers "how often did
this rider's attempts fail" (a rider-performance question — every failed knock on a door is a
data point about that rider, regardless of how many times the same parcel comes back around). The
two modules are deliberately asking different questions of the same failed-attempt scans; the
numbers correctly do not match, and R1 and R3 are not meant to reconcile against each other on this
count.

---

## D5 — Company average productivity (π̄)

**The ambiguity.** §4.2 says π̄ "is computed over all riders" without saying whether it is a mean
of means or a ratio of totals — `sum(π_r) / rider_count` and
`sum(n_del_r) / sum(d_r)` give different numbers whenever riders have unequal duty-day counts.

**Resolution.** π̄ is the **arithmetic mean of individual rider productivities**:
`π̄ = sum(π_r for each rider) / rider_count`. The coaching threshold is `0.7 × π̄`, computed and
compared against **unrounded** `π_r` and π̄, then displayed rounded to 1 decimal place
(`0.7 × 19.5 = 13.65`, displayed as `13.7`, matching the R3 footer in the PDF exactly).

**Why mean-of-means over total-ratio.** Only the mean-of-means reading reproduces the PDF's stated
`π̄ = 19.5` and threshold `13.7` against the worked rider figures once the generator's other riders
are added (verified numerically in `scripts/generate_data.py`); a totals-ratio would weight
high-duty-day riders more heavily and land on a different figure. The mean-of-means reading is also
the more natural interpretation of "coaching for underperforming riders" — it compares each rider
to the average *rider*, not to the average *duty-day*.

---

## D6 — R1 totals-row rounding discrepancy

**The contradiction.** The PDF's R1 totals row states an on-time rate of 89.5%. But its own
per-zone figures imply: `205 (Z-MIR) + 172 (Z-UTT) + 125 (Z-DHN) = 502` on-time parcels out of
`562` delivered, which is `502 / 562 = 89.3%`, not 89.5%. The PDF is internally inconsistent by
roughly one parcel's worth of rounding.

**Resolution.** The **per-zone figures are authoritative** — they appear in the §3.3 worked example
and are exactly what the Zone Performance Enquiry Form (§3.4) and `scripts/verify.py` check parcel
by parcel. The totals row is computed honestly from the real per-zone data in the seeded database,
and will correctly display 89.3%, not the PDF's 89.5%.

**Why not "fix" the data to hit 89.5% instead.** Forcing the totals to read 89.5% would require
either fabricating a 563rd on-time parcel that doesn't correspond to any zone's figures, or
silently shifting one of the three verified per-zone numbers — either way breaking a number that
*is* independently checked (the per-zone figures) to satisfy one that draws only on secondary
prose. Reporting the true, honestly-computed total and documenting the one-parcel discrepancy here
is more defensible at the viva than quietly reconciling it.

---

## D7 — Weekly report (R2) period

**The contradiction.** The PDF labels R2 "Week 27, 2026." ISO week 27 of 2026 runs 29 June –
5 July 2026. But R2's own figures are for a period that must include 8 July 2026 (it is meant to
align with the R1 date used throughout the rest of the document), which week 27 does not contain.

**Resolution.** R2 takes a single **end date** as its parameter and reports the **trailing 7-day
window ending on that date, inclusive** (i.e. `end_date − 6 days` through `end_date`). The report
is labelled with the explicit date range and the ISO week number *of the end date* — e.g.
"7-day period: 02 July – 08 July 2026 (ISO week 28)" — rather than a bare week number.

**Why this sidesteps the ambiguity rather than resolving it.** There is no consistent choice of
"the week" that both matches an ISO week number *and* ends on 8 July, because 8 July falls in ISO
week 28, not 27. Rather than guess which the PDF's author intended (a mislabelled week number, or a
non-ISO week definition), R2 is defined the way an operations manager would actually use it — "show
me the last 7 days as of today" — and the label states the real date range plainly so it is never
ambiguous what the figures cover.

---

## D8 — M4 secondary percentages are illustrative

**The problem.** The §6.3 worked example is fully specified and internally consistent: parcel
`PC-77012`'s address (`{section, pallabi, mirpur, kazipara, school}`, 5 terms) scores exactly
`4 / (√5 · √5) = 0.80 = 80%` against Z-MIR's description
(`{mirpur, pallabi, kazipara, shewrapara, section}`, 5 terms, sharing 4 terms). That part
reproduces exactly. But the PDF also states, without full specification, that the same address
scores 16% against Z-UTT (§6.3), that R5 shows PC-77013 at 91% against Z-UTT and PC-77020 at 42%
against no zone, and that R5's summary line reads "auto-assigned 601 of 655 (91.8%)." These
figures are not mutually satisfiable by any single, consistently-applied zone-description
vocabulary — e.g., landing PC-77012 on exactly 16% against Z-UTT requires Z-UTT's description to
hold 8 distinct terms sharing exactly 1 with PC-77012's address (`1/(√5·√8) = 0.158 → 16%`), while
landing some *other* address at 91% against Z-UTT requires a near-total 3-term overlap against an
~3-term description — there is no single Z-UTT description that supports both without being
rewritten between examples.

**Resolution.** Guarantee the fully-specified case exactly: `PC-77012` scores exactly 0.80 against
Z-MIR and is auto-assigned. For the Z-UTT secondary figure, author Z-UTT's description with
**8 distinct cleaned terms, sharing exactly one term with PC-77012's address** (`school`), which
yields `1 / (√5 · √8) = 0.1581 → 15.8%`, displayed per D10's integer rounding as **16%** — matching
the PDF's stated secondary figure exactly, by construction. The remaining scattered figures (R5's
91%, 42%, and the 91.8% summary line) are treated as illustrative rather than reproduced exactly;
they are left to fall out naturally from the real generated data and demo addresses instead of
being hand-forced, and are noted here as such.

**Why guarantee only two figures instead of trying to satisfy all of them.** The 80% case is the
one worked through step-by-step with an auditable calculation in the PDF — an examiner can and will
recompute it by hand. The 16% figure is the direct corollary the same paragraph draws from it
("confirming the assignment"). The other figures appear only as unexplained sample rows in R5 with
no shown working; treating those as illustrative sample output (which is exactly how R5 is
introduced — "Sample formats with values follow") rather than pinned targets avoids constructing an
artificial, self-contradictory zone vocabulary purely to chase numbers that were never derived from
a specified method in the first place.

---

## D9 — Deposits are a fifth input dataset

**The gap.** §1 opens by saying "the system reads four input data sets" and lists parcels, scans,
riders, and zones. But §5.2's Eq. (8), `Δ_r = C_r − G_r`, requires `G_r` — cash the rider *actually
deposited* — which is not derivable from any of the four listed datasets (parcel COD amounts give
what was *collected*, `C_r`, not what was *deposited*). §1's own prose says the cash office
"already record[s] cash-on-delivery (COD) collections **and deposits**," directly implying deposit
records exist as a distinct, pre-existing dataset even though §1's numbered list only names four.

**Resolution.** Add a fifth read-only input dataset, `deposits (rider_id, deposit_date, amount)`,
populated the same way as the other four (see D10.5) and never written to by the running
application. It is documented here as derived directly from §1's own cash-office sentence, not
invented independently of the spec.

---

## D10.5 — How data enters the system without violating the no-CRUD rule

**The apparent tension.** The hard constraint (`BUILD_PROMPT.md` §2, and the PDF's own §8
"Constraint reminder") is that CPDAS must contain no add, update, or delete operation against the
five input datasets. Yet a SQLite database with empty tables is useless — the data has to get in
somehow.

**Resolution.** §1 itself frames all datasets as already captured by systems outside CPDAS: the
booking counters "already record every parcel," the riders' handheld app "already records every
scan," and the cash office "already records" COD collections and deposits. CPDAS's stated purpose
is only "to analyse the stored data" — it is explicitly *not* the system of record that captures
it. Accordingly, the Flask application (`app.py`, `db.py`, everything under `modules/`) never
writes to `parcels`, `scans`, `riders`, `zones`, or `deposits` — it only ever runs `SELECT`
queries against them. The one and only population of those five tables happens **offline, once,
before the web server ever starts**, via `scripts/seed.py`, which loads CSV files produced by
`scripts/generate_data.py`.

This offline step is not a feature of the graded application. It plays the same role that a
one-time CSV import or ETL job would play in handing off data from a real courier company's
existing upstream systems (booking counters, handheld scanner app, cash office) into an analytics
database — exactly the situation §1 describes. It never runs while the app is serving requests,
and `scripts/verify.py`'s CRUD audit (§10 of `BUILD_PROMPT.md`) explicitly excludes
`scripts/seed.py` from its grep for `INSERT`/`UPDATE`/`DELETE`, for this same reason: that script
is the data hand-off, not the analytics system.

The one deliberate exception is `zone_assignments`, which is CPDAS's own computed *output*, not
one of the five business datasets — see D2. It is INSERT-only from within the running app itself,
which is consistent with the no-CRUD rule because the rule targets the five business datasets, and
`zone_assignments` is never updated or deleted even by the app.

---

## D10 — Display precision

Computation and display are kept strictly separate: **every formula is always computed and
stored/passed at full floating-point precision; rounding happens only at the last step, in the
template or formatting function that renders a value.** Threshold comparisons (85% for the
operations-review flag, 15% for the M2 coaching FailRate, 0.5% for the M3 escalation
ShortageRate, 0.80 for the M4 similarity cutoff, `0.7 × π̄` for M2 coaching) are always evaluated
against unrounded values, never against an already-rounded display string.

Display rules:

| Value type | Precision |
|---|---|
| Percentages in M1, M2, M3 and reports R1–R4 | 1 decimal place |
| Hours (delivery time) | 1 decimal place |
| Similarity percentages in M4 and R5 | integer |
| Currency (BDT) | thousands separators, no decimal places |
| Similarity threshold comparison | `>= 0.80` (exact worked example lands on 0.80 and auto-assigns) |

**Why compute-full/round-late matters here specifically.** Several worked examples in the PDF only
land on their stated figures because a threshold is compared before rounding — e.g. the coaching
threshold `0.7 × 19.5 = 13.65` must compare rider productivities against `13.65`, not the
*displayed* `13.7`, or a rider with true productivity `13.6` would be incorrectly placed on the
coaching list despite reading below the *displayed* threshold. Rounding early would silently shift
which side of a threshold borderline values fall on.
