"""Deterministic seed-data generator for CPDAS.

Run this once (scripts/setup.bat / setup.sh does it automatically) to produce
the CSV files in data/ that scripts/seed.py loads into the SQLite database.
The RNG is seeded with a fixed constant so re-running this script always
produces the same output. This is the one-time, offline data hand-off
described in decision D10.5 of docs/SPEC_DECISIONS.md -- it plays the role of
the upstream booking-counter / handheld-app / cash-office systems the
specification presupposes already exist. It is not part of the graded
application and never runs while the web server is serving requests.

This script reproduces, exactly, every worked-example figure in the faculty
specification (see BUILD_PROMPT.md Section 5 and docs/SPEC_DECISIONS.md).
Where the spec leaves the data free (ordinary day-to-day volume, most riders'
exact attempt counts, most addresses) the generator fills in plausible
randomised data, using a "residual" technique for every value that must land
on an exact target: draw all-but-one value randomly within a realistic
range, then set the last value to whatever residual is needed to hit the
target exactly, retrying the draw if that residual falls outside the
realistic range.
"""

import csv
import random
import sys
from datetime import date, datetime, timedelta
from fractions import Fraction
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from modules.text_similarity import binary_cosine_similarity, clean_terms

RNG_SEED = 4702026  # CSC 470, Project 13 -- fixed so output is reproducible.
random.seed(RNG_SEED)

DATA_DIR = Path(__file__).resolve().parent.parent / "data"

SIMILARITY_THRESHOLD = 0.80
# Floating-point sqrt arithmetic can land a "true" 0.80 score a hair below
# 0.80 (e.g. 0.7999999999999998), so >= comparisons against the threshold
# use this epsilon. modules/m4_matching.py uses the same constant.
SIMILARITY_EPSILON = 1e-9

TODAY = date(2026, 7, 8)
WEEK_START = TODAY - timedelta(days=6)  # 2026-07-02, per decision D7
JUNE_START = date(2026, 6, 1)
JUNE_END = date(2026, 6, 30)


# ---------------------------------------------------------------------------
# Small numeric helpers: the "residual technique" used throughout this file.
# ---------------------------------------------------------------------------

def split_int_with_residual(total, count, low, high, max_attempts=50000):
    """Split integer `total` into `count` integers, each in [low, high], that
    sum to exactly `total`.

    Draws `count - 1` random integers in range, then sets the last one to
    whatever residual is needed to reach `total` exactly. If that residual
    falls outside [low, high], the whole draw is retried. This is the
    "generate n-1, solve the nth as a residual, retry if unrealistic"
    technique BUILD_PROMPT.md prescribes for the M1 delivery-time sum and the
    M3 COD sum, generalised to integer counts.

    The n-1 values are drawn from a band centred on the target average
    (total / count), not the full [low, high] range -- see the docstring of
    split_float_with_residual for why that matters whenever the target
    average sits far from the midpoint of [low, high].
    """
    if count == 1:
        assert low <= total <= high, (total, count, low, high)
        return [total]

    target_avg = total / count
    max_half_width = min(target_avg - low, high - target_avg, (high - low) * 0.25)
    if max_half_width <= 0:
        band_low, band_high = low, high
    else:
        band_low = int(target_avg - max_half_width)
        band_high = int(target_avg + max_half_width) + 1
        band_low = max(low, band_low)
        band_high = min(high, band_high)

    for _attempt in range(max_attempts):
        values = [random.randint(band_low, band_high) for _ in range(count - 1)]
        residual = total - sum(values)
        if low <= residual <= high:
            values.append(residual)
            random.shuffle(values)
            return values
    raise RuntimeError(
        f"split_int_with_residual: could not split {total} into {count} "
        f"values in [{low},{high}] after {max_attempts} attempts"
    )


def split_float_with_residual(total, count, low, high, max_attempts=50000):
    """Same idea as split_int_with_residual, but for continuous values
    (delivery-time hours, COD amounts in taka).

    The n-1 non-residual values are drawn from a band centred on the target
    average (total / count) rather than uniformly across the whole
    [low, high] range. A uniform draw across the full range averages near
    its midpoint, so whenever the true target average sits far from that
    midpoint (e.g. a required average of 28h in a realistic 26-90h range),
    the residual would almost never land back in range. Centring the band on
    the target average keeps the technique reliable regardless of where in
    [low, high] that average falls.
    """
    if count == 1:
        assert low <= total <= high, (total, count, low, high)
        return [total]

    target_avg = total / count
    # Keep the band symmetric AROUND the target average -- clamping only one
    # side (e.g. when the target average sits near `low`) would leave the
    # band's own average shifted away from the target, defeating the point.
    max_half_width = min(target_avg - low, high - target_avg, (high - low) * 0.25)
    if max_half_width <= 0:
        band_low, band_high = low, high
    else:
        band_low = target_avg - max_half_width
        band_high = target_avg + max_half_width

    for _attempt in range(max_attempts):
        values = [random.uniform(band_low, band_high) for _ in range(count - 1)]
        residual = total - sum(values)
        if low <= residual <= high:
            values.append(residual)
            random.shuffle(values)
            return values
    raise RuntimeError(
        f"split_float_with_residual: could not split {total} into {count} "
        f"values in [{low},{high}] after {max_attempts} attempts"
    )


def _rounds_half_up(value, ndigits):
    """Round-half-up, matching decision D10's display rule.

    Python's built-in round() uses round-half-to-even, which would display
    the exact 13.65 threshold worked example as 13.6 instead of the PDF's
    stated 13.7 -- so every display value in this project rounds half up.
    """
    from decimal import ROUND_HALF_UP, Decimal
    quantum = Decimal("1").scaleb(-ndigits)
    return float(Decimal(str(value)).quantize(quantum, rounding=ROUND_HALF_UP))


def daterange(start, end):
    """All dates from start to end, inclusive."""
    days = (end - start).days
    return [start + timedelta(days=offset) for offset in range(days + 1)]


# ---------------------------------------------------------------------------
# Zones
# ---------------------------------------------------------------------------

# Descriptions are hand-authored and their cleaned term sets are verified
# programmatically below (verify_zone_term_sets) rather than assumed -- see
# decision D8. Z-MIR's terms and PC-77012's address terms are taken directly
# from the section 6.3 worked example. Z-UTT is authored to hold exactly 8
# distinct terms sharing exactly one term ("school") with PC-77012's address,
# which is what makes the secondary 16% figure in that same worked example
# reproduce exactly (1 / (sqrt(5) * sqrt(8)) = 0.1581 -> displays as 16%).
ZONES = [
    {
        "zone_id": "Z-MIR",
        "zone_name": "Mirpur",
        "hub": "Mirpur Hub",
        "description": "Mirpur, Pallabi, Kazipara, Shewrapara, Section 1-14",
    },
    {
        "zone_id": "Z-UTT",
        "zone_name": "Uttara",
        "hub": "Uttara Hub",
        "description": (
            "Uttara Sector 3, Sector 7, Rajlokkhi, Kuril, Azampur, "
            "Jasimuddin Road, near Uttara School, Airport Road"
        ),
    },
    {
        "zone_id": "Z-DHN",
        "zone_name": "Dhanmondi",
        "hub": "Dhanmondi Hub",
        "description": (
            "Dhanmondi, Road 27, Satmasjid Road, Kalabagan, Rayerbazar, "
            "near Dhanmondi Lake, Hatirpool"
        ),
    },
]

PC_77012_ADDRESS = "House 12, Road 3, Section 7, Pallabi, Mirpur, opposite Kazipara school"


def verify_zone_term_sets():
    """Assert the zone descriptions clean to the exact term sets decision D8
    requires, instead of assuming the hand-authored text is correct."""
    terms_by_zone = {zone["zone_id"]: clean_terms(zone["description"]) for zone in ZONES}

    expected_mir_terms = {"mirpur", "pallabi", "kazipara", "shewrapara", "section"}
    assert terms_by_zone["Z-MIR"] == expected_mir_terms, terms_by_zone["Z-MIR"]

    assert len(terms_by_zone["Z-UTT"]) == 8, terms_by_zone["Z-UTT"]
    assert 5 <= len(terms_by_zone["Z-DHN"]) <= 8, terms_by_zone["Z-DHN"]

    pc_terms = clean_terms(PC_77012_ADDRESS)
    expected_pc_terms = {"section", "pallabi", "mirpur", "kazipara", "school"}
    assert pc_terms == expected_pc_terms, pc_terms

    shared_with_utt = terms_by_zone["Z-UTT"] & pc_terms
    assert shared_with_utt == {"school"}, shared_with_utt
    shared_with_dhn = terms_by_zone["Z-DHN"] & pc_terms
    assert shared_with_dhn == set(), shared_with_dhn

    sim_mir = binary_cosine_similarity(pc_terms, terms_by_zone["Z-MIR"])
    assert abs(sim_mir - 0.80) < 1e-9, sim_mir

    sim_utt = binary_cosine_similarity(pc_terms, terms_by_zone["Z-UTT"])
    assert round(sim_utt * 100) == 16, sim_utt

    return terms_by_zone


ZONE_TERMS = verify_zone_term_sets()


def score_against_all_zones(address_terms):
    """Score a cleaned address-term set against every zone.

    Returns a list of (zone_id, score) sorted best-first. This is the same
    computation modules/m4_matching.py performs at request time (Eq. 10) --
    used here to precompute the zone assignment for every historical parcel
    exactly as the AI-matching module would have, at the time it was
    originally processed (see the D2 addendum in docs/SPEC_DECISIONS.md).
    """
    scored = []
    for zone in ZONES:
        score = binary_cosine_similarity(address_terms, ZONE_TERMS[zone["zone_id"]])
        scored.append((zone["zone_id"], score))
    scored.sort(key=lambda pair: pair[1], reverse=True)
    return scored


# ---------------------------------------------------------------------------
# Riders
# ---------------------------------------------------------------------------

# The three riders whose figures are pinned exactly by the PDF's worked
# examples (Section 4.3 for M2, R3/R4 for the reports).
FIXED_RIDERS = [
    {"rider_id": "RD-114", "name": "Sumon Mia", "home_zone": "Z-MIR", "duty_days": 24, "delivered": 508, "failed": 52},
    {"rider_id": "RD-108", "name": "Alamgir Hossain", "home_zone": "Z-UTT", "duty_days": 25, "delivered": 472, "failed": 61},
    {"rider_id": "RD-131", "name": "Liton Sarker", "home_zone": "Z-DHN", "duty_days": 23, "delivered": 296, "failed": 64},
]

# Additional riders needed to bring the roster to 8 (decision D5): their
# delivered/duty-day figures are solved below so the arithmetic mean of all
# 8 riders' productivities rounds to 19.5, matching the PDF's stated company
# average and the resulting 13.7 coaching threshold.
EXTRA_RIDER_INFO = [
    ("RD-101", "Kamal Uddin", "Z-MIR"),
    ("RD-102", "Nasrin Akter", "Z-UTT"),
    ("RD-103", "Habibur Rahman", "Z-DHN"),
    ("RD-105", "Shirin Begum", "Z-MIR"),
    ("RD-107", "Delwar Hossain", "Z-UTT"),
]

TARGET_MEAN_PRODUCTIVITY = Fraction(39, 2)  # 19.5 -- decision D5


def solve_extra_riders():
    """Solve delivered/duty-day figures for the 5 extra riders.

    Four of the five get a chosen duty-day count and a "nice" target
    productivity; their delivered totals are that productivity times duty
    days, rounded to an integer. The fifth rider's delivered total is then
    solved exactly with Fraction arithmetic (not floats, to avoid rounding
    drift) so the arithmetic mean productivity across all 8 riders lands on
    19.5 -- see decision D5. Same residual idea as split_int_with_residual,
    but solved exactly since there are only 8 terms in the mean.
    """
    riders = []
    chosen_plans = [
        ("RD-101", 22, Fraction(20, 1)),
        ("RD-102", 25, Fraction(22, 1)),
        ("RD-103", 24, Fraction(35, 2)),   # 17.5
        ("RD-105", 26, Fraction(24, 1)),
    ]
    for rider_id, duty_days, target_productivity in chosen_plans:
        delivered = round(target_productivity * duty_days)
        riders.append({"rider_id": rider_id, "duty_days": duty_days, "delivered": delivered})

    known_sum = sum(Fraction(r["delivered"], r["duty_days"]) for r in FIXED_RIDERS + riders)
    total_rider_count = len(FIXED_RIDERS) + len(EXTRA_RIDER_INFO)
    target_sum = TARGET_MEAN_PRODUCTIVITY * total_rider_count
    needed_productivity = target_sum - known_sum

    # The nearest integer delivered-count for the 8th rider gets us close to
    # a 19.5 mean, but rounding can push the *true* mean to just below 19.5,
    # which would round the 0.7x threshold down to 13.6 instead of 13.7.
    # Search outward from the nearest integer for the smallest delivered
    # count whose resulting mean displays as 19.5 with a 13.7 threshold.
    last_duty_days = 24
    candidate = round(needed_productivity * last_duty_days)
    last_delivered = None
    for offset in range(0, 20):
        for trial in (candidate + offset, candidate - offset):
            trial_pi = Fraction(trial, last_duty_days)
            trial_mean = (known_sum + trial_pi) / total_rider_count
            if round(float(trial_mean), 1) == 19.5 and _rounds_half_up(float(trial_mean) * 0.7, 1) == 13.7:
                last_delivered = trial
                break
        if last_delivered is not None:
            break
    assert last_delivered is not None, "could not find a valid 8th-rider delivered count"
    riders.append({"rider_id": "RD-107", "duty_days": last_duty_days, "delivered": last_delivered})

    info_by_id = {rider_id: (name, zone) for rider_id, name, zone in EXTRA_RIDER_INFO}
    for rider in riders:
        name, home_zone = info_by_id[rider["rider_id"]]
        rider["name"] = name
        rider["home_zone"] = home_zone
        # Failed-attempt count: not an examined figure for these riders, so
        # just pick a plausible fail rate (5-14%) relative to delivered.
        fail_rate = random.uniform(0.05, 0.14)
        rider["failed"] = round(rider["delivered"] * fail_rate / (1 - fail_rate))
    return riders


EXTRA_RIDERS = solve_extra_riders()
ALL_RIDERS = FIXED_RIDERS + EXTRA_RIDERS
RIDER_IDS = [r["rider_id"] for r in ALL_RIDERS]


def verify_rider_productivity():
    """Assert the mean productivity and coaching threshold match the PDF."""
    productivities = [Fraction(r["delivered"], r["duty_days"]) for r in ALL_RIDERS]
    mean_productivity = sum(productivities) / len(productivities)
    mean_float = float(mean_productivity)
    assert round(mean_float, 1) == 19.5, mean_float

    threshold = 0.7 * mean_float
    assert _rounds_half_up(threshold, 1) == 13.7, threshold

    rd114_pi = Fraction(508, 24)
    rd108_pi = Fraction(472, 25)
    rd131_pi = Fraction(296, 23)
    assert float(rd114_pi) >= threshold, (float(rd114_pi), threshold)
    assert float(rd108_pi) >= threshold, (float(rd108_pi), threshold)
    assert float(rd131_pi) < threshold, (float(rd131_pi), threshold)

    return mean_float, threshold


MEAN_PRODUCTIVITY, COACHING_THRESHOLD = verify_rider_productivity()


# ---------------------------------------------------------------------------
# Output collectors
# ---------------------------------------------------------------------------

parcels_rows = []          # dict rows for data/parcels.csv
scans_rows = []             # dict rows for data/scans.csv
zone_assignments_rows = []  # dict rows for data/zone_assignments.csv
deposits_rows = []          # dict rows for data/deposits.csv

_parcel_counter = 100000
_scan_counter = 0


def next_parcel_id():
    global _parcel_counter
    _parcel_counter += 1
    return f"PC-{_parcel_counter}"


def next_scan_id():
    global _scan_counter
    _scan_counter += 1
    return _scan_counter


# ---------------------------------------------------------------------------
# Address text generation
# ---------------------------------------------------------------------------

# House/road numbers and a positional stop-word are added for surface realism;
# the tokenizer strips all of it back out (see modules/text_similarity.py),
# so it never changes the cleaned term set or the similarity score.
ADDRESS_PREFIXES = ["House {n}, Road {n2}, ", "House {n}, ", "Flat {n}, Road {n2}, ", ""]
ADDRESS_LANDMARK_PREFIXES = ["near ", "beside ", "opposite ", ""]


def make_zone_flavoured_address(zone_id, drop_one_term=False):
    """Build a free-text address whose cleaned terms come from the given
    zone's own description, so it is guaranteed to score highly against that
    zone under Eq. (10). Occasionally drops one term for mild variety while
    staying safely above the 0.80 auto-assign threshold."""
    zone = next(z for z in ZONES if z["zone_id"] == zone_id)
    core_terms = list(ZONE_TERMS[zone_id])
    if drop_one_term and len(core_terms) > 4:
        core_terms = core_terms[:-1]
    random.shuffle(core_terms)

    prefix = random.choice(ADDRESS_PREFIXES).format(n=random.randint(1, 40), n2=random.randint(1, 27))
    landmark_prefix = random.choice(ADDRESS_LANDMARK_PREFIXES)
    body = ", ".join(term.capitalize() for term in core_terms)
    if landmark_prefix:
        body = f"{landmark_prefix}{body}"
    return f"{prefix}{body}, {zone['zone_name']}"


def verify_address_matches_zone(address, expected_zone_id):
    terms = clean_terms(address)
    scores = score_against_all_zones(terms)
    best_zone_id, best_score = scores[0]
    assert best_zone_id == expected_zone_id, (address, scores)
    assert best_score >= SIMILARITY_THRESHOLD - SIMILARITY_EPSILON, (address, scores)
    return best_score


# ---------------------------------------------------------------------------
# Parcel / scan creation helpers
# ---------------------------------------------------------------------------

FAILURE_REASON_POOL = [
    "customer unreachable",
    "address not found",
    "customer refused",
    "cod not ready",
    "shop closed",
]


def record_zone_assignment(parcel_id, zone_id, score, created_at):
    zone_assignments_rows.append({
        "parcel_id": parcel_id,
        "zone_id": zone_id,
        "similarity_score": round(score, 6),
        "source": "auto",
        "created_at": created_at.strftime("%Y-%m-%d %H:%M:%S"),
    })


def create_delivered_parcel(zone_id, delivered_date, delivery_hours, promised_hours, rider_id, cod_amount=0.0):
    """Create one parcel that resolves to 'delivered' on delivered_date, with
    total delivery time (Eq. 2) equal to delivery_hours."""
    parcel_id = next_parcel_id()
    delivered_at = datetime.combine(delivered_date, datetime.min.time()) + timedelta(
        hours=random.uniform(9, 20)
    )
    booked_at = delivered_at - timedelta(hours=delivery_hours)
    hub_out_at = booked_at + timedelta(hours=random.uniform(0.5, 4))

    address = make_zone_flavoured_address(zone_id, drop_one_term=random.random() < 0.1)
    score = verify_address_matches_zone(address, zone_id)

    parcels_rows.append({
        "parcel_id": parcel_id,
        "booked_at": booked_at.strftime("%Y-%m-%d %H:%M:%S"),
        "promised_hours": promised_hours,
        "delivery_address": address,
        "cod_amount": round(cod_amount, 2),
    })
    scans_rows.append({
        "scan_id": next_scan_id(), "parcel_id": parcel_id, "scan_type": "hub_out",
        "rider_id": rider_id, "scanned_at": hub_out_at.strftime("%Y-%m-%d %H:%M:%S"),
        "failure_reason": "",
    })
    scans_rows.append({
        "scan_id": next_scan_id(), "parcel_id": parcel_id, "scan_type": "delivered",
        "rider_id": rider_id, "scanned_at": delivered_at.strftime("%Y-%m-%d %H:%M:%S"),
        "failure_reason": "",
    })
    record_zone_assignment(parcel_id, zone_id, score, booked_at + timedelta(minutes=10))
    return parcel_id


def create_failed_parcel(zone_id, failed_date, rider_id, failure_reason, extra_attempts=0):
    """Create one parcel whose resolved outcome (decision D3) on failed_date
    is 'failed'. `extra_attempts` adds additional failed_attempt scan rows on
    the same date, for the decision-D4 demonstration that M2 counts scan
    rows while M1 counts distinct parcels."""
    parcel_id = next_parcel_id()
    failed_at = datetime.combine(failed_date, datetime.min.time()) + timedelta(hours=random.uniform(9, 20))
    booked_at = failed_at - timedelta(hours=random.uniform(6, 30))
    hub_out_at = booked_at + timedelta(hours=random.uniform(0.5, 4))

    address = make_zone_flavoured_address(zone_id, drop_one_term=random.random() < 0.1)
    score = verify_address_matches_zone(address, zone_id)

    parcels_rows.append({
        "parcel_id": parcel_id,
        "booked_at": booked_at.strftime("%Y-%m-%d %H:%M:%S"),
        "promised_hours": random.choice([24, 48, 72]),
        "delivery_address": address,
        "cod_amount": 0.0,
    })
    scans_rows.append({
        "scan_id": next_scan_id(), "parcel_id": parcel_id, "scan_type": "hub_out",
        "rider_id": rider_id, "scanned_at": hub_out_at.strftime("%Y-%m-%d %H:%M:%S"),
        "failure_reason": "",
    })
    scans_rows.append({
        "scan_id": next_scan_id(), "parcel_id": parcel_id, "scan_type": "failed_attempt",
        "rider_id": rider_id, "scanned_at": failed_at.strftime("%Y-%m-%d %H:%M:%S"),
        "failure_reason": failure_reason,
    })
    for _ in range(extra_attempts):
        retry_at = failed_at + timedelta(hours=random.uniform(0.5, 3))
        scans_rows.append({
            "scan_id": next_scan_id(), "parcel_id": parcel_id, "scan_type": "failed_attempt",
            "rider_id": rider_id, "scanned_at": retry_at.strftime("%Y-%m-%d %H:%M:%S"),
            "failure_reason": random.choice(FAILURE_REASON_POOL),
        })
    record_zone_assignment(parcel_id, zone_id, score, booked_at + timedelta(minutes=10))
    return parcel_id


def create_in_transit_parcel(zone_id, booked_date):
    """A parcel with only a hub_out scan -- excluded entirely from that
    date's M1 figures, per decision D3."""
    parcel_id = next_parcel_id()
    booked_at = datetime.combine(booked_date, datetime.min.time()) + timedelta(hours=random.uniform(9, 21))
    hub_out_at = booked_at + timedelta(hours=random.uniform(0.5, 4))
    address = make_zone_flavoured_address(zone_id)
    score = verify_address_matches_zone(address, zone_id)

    parcels_rows.append({
        "parcel_id": parcel_id,
        "booked_at": booked_at.strftime("%Y-%m-%d %H:%M:%S"),
        "promised_hours": random.choice([24, 48, 72]),
        "delivery_address": address,
        "cod_amount": 0.0,
    })
    scans_rows.append({
        "scan_id": next_scan_id(), "parcel_id": parcel_id, "scan_type": "hub_out",
        "rider_id": random.choice(RIDER_IDS), "scanned_at": hub_out_at.strftime("%Y-%m-%d %H:%M:%S"),
        "failure_reason": "",
    })
    record_zone_assignment(parcel_id, zone_id, score, booked_at + timedelta(minutes=10))
    return parcel_id


# ---------------------------------------------------------------------------
# M1 / R1 / R2: 08 July exact zone figures + the 7-day window (decision D7)
# ---------------------------------------------------------------------------

# zone_id -> (attempted, delivered, failed, on_time_count) on 2026-07-08.
# Exact figures from BUILD_PROMPT.md Section 5, reproducing Section 3.3 and
# Section 7.1 of the PDF.
DAY08_TARGETS = {
    "Z-MIR": {"attempted": 250, "delivered": 228, "failed": 22, "on_time": 205},
    "Z-UTT": {"attempted": 198, "delivered": 186, "failed": 12, "on_time": 172},
    "Z-DHN": {"attempted": 174, "delivered": 148, "failed": 26, "on_time": 125},
}

# Weekly (7-day window ending 08 July) targets from R2 -- Section 7.2 of the PDF.
WEEK_TARGETS = {
    "Z-MIR": {"avg_time": 33.0, "success_pct": 90.8, "volume": 1702},
    "Z-UTT": {"avg_time": 29.4, "success_pct": 94.1, "volume": 1310},
    "Z-DHN": {"avg_time": 41.6, "success_pct": 83.9, "volume": 1166},
}

# Every day in the 7-day window has the SAME average delivery time as the
# window's own reported average (Z-MIR's single day 08 July already proves
# this: 7524.0 / 228 = 33.0h exactly, matching R2's weekly average exactly).
# Applying that same daily average uniformly across the whole window makes
# the weekly average trivially exact without needing a second residual solve
# on top of the daily one.
ZONE_AVG_TIME = {zone_id: targets["avg_time"] for zone_id, targets in WEEK_TARGETS.items()}

# Z-DHN's 3-consecutive-day operations-review flag (decision, BUILD_PROMPT.md
# Section 5): below 85% success on 04-06 July, but NOT on 08 July itself.
DHN_FLAG_DAYS = {
    date(2026, 7, 4): {"attempted": 160, "delivered": 128},   # 80.0%
    date(2026, 7, 5): {"attempted": 150, "delivered": 122},   # 81.3%
    date(2026, 7, 6): {"attempted": 145, "delivered": 121},   # 83.4%
}
for _day, _figures in DHN_FLAG_DAYS.items():
    _success = _figures["delivered"] / _figures["attempted"] * 100
    assert _success < 85.0, (_day, _success)


def generate_delivered_batch(zone_id, delivered_date, count, target_avg_time, on_time_count=None):
    """Create `count` delivered parcels for zone_id on delivered_date whose
    total delivery time sums to count * target_avg_time exactly (Eq. 4).

    If on_time_count is given, exactly that many of the parcels are on-time
    (T_p <= promised_hours) and the rest are late -- used for the three exact
    on-time counts on 08 July (decision-checked figures). Otherwise on-time
    status is left to fall out naturally from randomly varied promised hours.
    """
    target_sum = count * target_avg_time
    rider_ids = []

    if on_time_count is None:
        # No exact on-time requirement: promised hours vary for realism
        # (BUILD_PROMPT.md Section 5), on-time status isn't tracked.
        promised_hours_list = [random.choice([24, 48, 72]) for _ in range(count)]
        times = split_float_with_residual(target_sum, count, 4.0, 90.0)
    else:
        # Exact on-time count required. Draw the on-time group's delivery
        # times from a strictly low range and the late group's from a
        # strictly high, non-overlapping range, so which group a parcel
        # belongs to is fixed by construction -- no need to re-check after
        # the fact. promised_hours is then assigned per parcel to match:
        # on-time parcels always get 72h (comfortably >= anything in the low
        # range), late parcels get 24h or 48h (comfortably < anything in the
        # high range). This keeps the search for a feasible split-point
        # entirely separate from the residual draw itself.
        assert 0 <= on_time_count <= count
        late_count = count - on_time_count
        promised_hours_list = [None] * count
        times = [None] * count

        on_time_low, on_time_high = 4.0, 70.0
        late_low, late_high = 26.0, 90.0

        # A margin keeps the chosen group averages strictly inside their
        # range (not just at the boundary) -- an average sitting exactly at
        # the edge of [low, high] is not actually drawable by "n-1 random +
        # 1 residual", since the residual would need every other draw to
        # land improbably close to that same edge.
        margin = 2.0

        on_time_sum = target_sum
        late_sum = 0.0
        if late_count > 0:
            found = False
            for step in range(81):
                late_avg_candidate = late_low + step * (late_high - late_low) / 80
                late_sum_candidate = late_count * late_avg_candidate
                on_time_sum_candidate = target_sum - late_sum_candidate
                if on_time_count > 0:
                    on_time_avg_candidate = on_time_sum_candidate / on_time_count
                    on_time_ok = (on_time_low + margin) <= on_time_avg_candidate <= (on_time_high - margin)
                else:
                    on_time_ok = abs(on_time_sum_candidate) < 1e-6
                late_ok = (late_low + margin) <= late_avg_candidate <= (late_high - margin)
                if on_time_ok and late_ok:
                    late_sum = late_sum_candidate
                    on_time_sum = on_time_sum_candidate
                    found = True
                    break
            assert found, (
                "generate_delivered_batch: no feasible on-time/late split for "
                f"{zone_id}/{delivered_date} (count={count}, on_time={on_time_count}, "
                f"target_avg={target_avg_time})"
            )

        on_time_times = split_float_with_residual(on_time_sum, on_time_count, on_time_low, on_time_high) if on_time_count > 0 else []
        late_times = split_float_with_residual(late_sum, late_count, late_low, late_high) if late_count > 0 else []

        for index, t in enumerate(on_time_times):
            times[index] = t
            if t <= 24:
                promised_hours_list[index] = random.choice([24, 48, 72])
            elif t <= 48:
                promised_hours_list[index] = random.choice([48, 72])
            else:
                promised_hours_list[index] = 72

        for offset, t in enumerate(late_times):
            index = on_time_count + offset
            times[index] = t
            promised_hours_list[index] = random.choice([24, 48]) if t > 48 else 24

    for index in range(count):
        rider_id = random.choice(RIDER_IDS)
        rider_ids.append(rider_id)
        create_delivered_parcel(
            zone_id, delivered_date, times[index], promised_hours_list[index], rider_id
        )

    if on_time_count is not None:
        actual_on_time = sum(1 for i in range(count) if times[i] <= promised_hours_list[i])
        assert actual_on_time == on_time_count, (zone_id, delivered_date, actual_on_time, on_time_count)


def generate_failed_batch(zone_id, failed_date, count, reasons=None):
    """Create `count` failed parcels for zone_id, resolved as 'failed' on
    failed_date (decision D3). `reasons` is an optional list of exactly
    `count` failure-reason strings; otherwise reasons are drawn at random."""
    if reasons is None:
        reasons = [random.choice(FAILURE_REASON_POOL) for _ in range(count)]
    assert len(reasons) == count
    for reason in reasons:
        rider_id = random.choice(RIDER_IDS)
        create_failed_parcel(zone_id, failed_date, rider_id, reason)


# --- 08 July: exact per-zone figures --------------------------------------

# R1's city-wide top failure reason: "customer unreachable (34 of 60)".
_day08_total_failed = sum(t["failed"] for t in DAY08_TARGETS.values())
assert _day08_total_failed == 60, _day08_total_failed
_day08_reason_pool = (
    ["customer unreachable"] * 34
    + ["address not found"] * 10
    + ["customer refused"] * 8
    + ["cod not ready"] * 5
    + ["shop closed"] * 3
)
assert len(_day08_reason_pool) == 60
random.shuffle(_day08_reason_pool)
_reason_cursor = 0

for _zone_id, _targets in DAY08_TARGETS.items():
    generate_delivered_batch(
        _zone_id, TODAY, _targets["delivered"], ZONE_AVG_TIME[_zone_id], on_time_count=_targets["on_time"]
    )
    _zone_reasons = _day08_reason_pool[_reason_cursor: _reason_cursor + _targets["failed"]]
    _reason_cursor += _targets["failed"]
    generate_failed_batch(_zone_id, TODAY, _targets["failed"], reasons=_zone_reasons)

assert _reason_cursor == 60

# --- Z-DHN's 04-06 July flag streak ----------------------------------------

for _day, _figures in DHN_FLAG_DAYS.items():
    generate_delivered_batch("Z-DHN", _day, _figures["delivered"], ZONE_AVG_TIME["Z-DHN"])
    generate_failed_batch("Z-DHN", _day, _figures["attempted"] - _figures["delivered"])

# --- Remaining days in the 7-day window: 02, 03, 07 for all zones,
#     and additionally 04, 05, 06 for Z-MIR / Z-UTT (which carry no flag
#     requirement, so their whole 6-day remainder is free). --------------

FREE_DAYS_ALL_ZONES = [date(2026, 7, 2), date(2026, 7, 3), date(2026, 7, 7)]
FREE_DAYS_NO_FLAG_ZONES = FREE_DAYS_ALL_ZONES + [date(2026, 7, 4), date(2026, 7, 5), date(2026, 7, 6)]


def fill_remaining_week_days(zone_id, free_days):
    target = WEEK_TARGETS[zone_id]
    already_attempted = DAY08_TARGETS[zone_id]["attempted"]
    already_delivered = DAY08_TARGETS[zone_id]["delivered"]
    if zone_id == "Z-DHN":
        for figures in DHN_FLAG_DAYS.values():
            already_attempted += figures["attempted"]
            already_delivered += figures["delivered"]

    remaining_attempted = target["volume"] - already_attempted
    target_total_delivered = round(target["volume"] * target["success_pct"] / 100)
    remaining_delivered = target_total_delivered - already_delivered

    n = len(free_days)
    avg_attempted = remaining_attempted / n
    low_att, high_att = int(avg_attempted * 0.75), int(avg_attempted * 1.25)
    attempted_values = split_int_with_residual(remaining_attempted, n, low_att, high_att)

    # Delivered per day must not exceed that day's attempted count; bound it
    # around the target success rate (+/- 6 points) so no single day looks
    # implausible next to the zone's real performance.
    target_rate = target["success_pct"] / 100
    for _attempt in range(20000):
        delivered_values = []
        feasible = True
        for attempted in attempted_values:
            low_del = max(0, int(attempted * max(0.0, target_rate - 0.06)))
            high_del = min(attempted, int(attempted * min(1.0, target_rate + 0.06)))
            if low_del > high_del:
                feasible = False
                break
            delivered_values.append((low_del, high_del))
        if not feasible:
            continue
        try:
            chosen = []
            for index in range(n - 1):
                low_del, high_del = delivered_values[index]
                chosen.append(random.randint(low_del, high_del))
            residual = remaining_delivered - sum(chosen)
            low_last, high_last = delivered_values[-1]
            if low_last <= residual <= high_last:
                chosen.append(residual)
                break
        except ValueError:
            continue
    else:
        raise RuntimeError(f"fill_remaining_week_days: could not solve delivered split for {zone_id}")

    total_delivered_check = already_delivered + sum(chosen)
    actual_rate = total_delivered_check / target["volume"] * 100
    assert round(actual_rate, 1) == target["success_pct"], (zone_id, actual_rate, target["success_pct"])

    for day, attempted, delivered in zip(free_days, attempted_values, chosen):
        generate_delivered_batch(zone_id, day, delivered, ZONE_AVG_TIME[zone_id])
        generate_failed_batch(zone_id, day, attempted - delivered)


fill_remaining_week_days("Z-MIR", FREE_DAYS_NO_FLAG_ZONES)
fill_remaining_week_days("Z-UTT", FREE_DAYS_NO_FLAG_ZONES)
fill_remaining_week_days("Z-DHN", FREE_DAYS_ALL_ZONES)


# ---------------------------------------------------------------------------
# In-transit parcels on 08 July (decision D3 demonstration): booked, hub_out
# scanned, but not yet resolved -- excluded entirely from that date's figures.
# ---------------------------------------------------------------------------

for _ in range(18):
    _zone_id = random.choice([z["zone_id"] for z in ZONES])
    create_in_transit_parcel(_zone_id, TODAY)


# ---------------------------------------------------------------------------
# Multi-attempt demonstration parcels (decision D4): a handful of parcels
# that fail more than once on the same day, kept well outside every exact
# verified window so they cannot disturb any of the totals above.
# ---------------------------------------------------------------------------

_MULTI_ATTEMPT_DATE = date(2026, 6, 15)
for _ in range(6):
    _zone_id = random.choice([z["zone_id"] for z in ZONES])
    create_failed_parcel(
        _zone_id, _MULTI_ATTEMPT_DATE, random.choice(RIDER_IDS),
        random.choice(FAILURE_REASON_POOL), extra_attempts=random.choice([1, 2]),
    )


# ---------------------------------------------------------------------------
# M3: COD reconciliation for 08 July -- decision constraint: only RD-114,
# RD-108 and RD-131 carry non-zero COD that day; every other rider's 08 July
# deliveries (already generated above with cod_amount=0) stay prepaid-only,
# and COD is left at 0 on every other date system-wide, so the M3 date-
# selector form is unambiguous for any date outside 08 July.
# ---------------------------------------------------------------------------

COD_TARGETS = {"RD-114": 38450.0, "RD-108": 31220.0, "RD-131": 27300.0}
DEPOSIT_SHORTAGE = {"RD-114": 0.0, "RD-108": 0.0, "RD-131": 1000.0}

# Delivered parcels created for 08 July, grouped by zone, so we can pick a
# subset of already-created (but still cod_amount == 0) parcels to carry the
# COD amounts, without disturbing the M1 figures already fixed above.
_day08_delivered_parcel_ids = [
    row["parcel_id"] for row in parcels_rows
    if row["booked_at"] < f"{TODAY.isoformat()} 24:00:00"
]


def find_day08_delivered_parcels(exclude_ids, count):
    """Pick `count` parcels that were delivered on 08 July (they have a
    'delivered' scan on that date) and are not already claimed for COD."""
    delivered_on_day08 = {
        row["parcel_id"] for row in scans_rows
        if row["scan_type"] == "delivered" and row["scanned_at"].startswith(TODAY.isoformat())
    }
    candidates = [pid for pid in delivered_on_day08 if pid not in exclude_ids]
    random.shuffle(candidates)
    return candidates[:count]


_claimed_parcel_ids = set()
_parcels_by_id = {row["parcel_id"]: row for row in parcels_rows}
_scans_by_parcel = {}
for _scan in scans_rows:
    _scans_by_parcel.setdefault(_scan["parcel_id"], []).append(_scan)

for _rider_id, _target_amount in COD_TARGETS.items():
    _cod_parcel_count = random.randint(9, 14)
    _chosen = find_day08_delivered_parcels(_claimed_parcel_ids, _cod_parcel_count)
    _claimed_parcel_ids.update(_chosen)

    _amounts = split_float_with_residual(_target_amount, len(_chosen), 300.0, 5500.0)
    for _parcel_id, _amount in zip(_chosen, _amounts):
        _parcels_by_id[_parcel_id]["cod_amount"] = round(_amount, 2)
        for _scan in _scans_by_parcel[_parcel_id]:
            _scan["rider_id"] = _rider_id

    _collected_check = round(sum(_amounts), 2)
    assert abs(_collected_check - _target_amount) < 0.01, (_rider_id, _collected_check, _target_amount)

    deposits_rows.append({
        "rider_id": _rider_id,
        "deposit_date": TODAY.isoformat(),
        "amount": round(_target_amount - DEPOSIT_SHORTAGE[_rider_id], 2),
    })


# ---------------------------------------------------------------------------
# M2: June 2026 monthly figures for all 8 riders.
# ---------------------------------------------------------------------------

# RD-114's failure-reason breakdown (Section 4.3 of the PDF): 31 "customer
# unreachable", 14 "address not found", 7 split across other reasons.
RD114_REASON_BREAKDOWN = (
    ["customer unreachable"] * 31
    + ["address not found"] * 14
    + ["customer refused"] * 4
    + ["cod not ready"] * 3
)
assert len(RD114_REASON_BREAKDOWN) == 52


def generate_june_rider_data(rider, reason_breakdown=None):
    rider_id = rider["rider_id"]
    home_zone = rider["home_zone"]
    duty_day_count = rider["duty_days"]
    delivered_total = rider["delivered"]
    failed_total = rider["failed"]

    june_days = daterange(JUNE_START, JUNE_END)
    duty_dates = sorted(random.sample(june_days, duty_day_count))

    delivered_per_day = split_int_with_residual(
        delivered_total, duty_day_count, max(1, delivered_total // duty_day_count - 6),
        delivered_total // duty_day_count + 6,
    )
    if failed_total > 0:
        failed_per_day = split_int_with_residual(
            failed_total, duty_day_count, 0, max(3, failed_total // duty_day_count + 3),
        )
    else:
        failed_per_day = [0] * duty_day_count

    if reason_breakdown is not None:
        reasons = list(reason_breakdown)
        random.shuffle(reasons)
    else:
        reasons = [random.choice(FAILURE_REASON_POOL) for _ in range(failed_total)]
    reason_cursor = 0

    for day_index, duty_date in enumerate(duty_dates):
        day_delivered = delivered_per_day[day_index]
        day_failed = failed_per_day[day_index]
        for _ in range(day_delivered):
            avg_time = ZONE_AVG_TIME.get(home_zone, 35.0)
            delivery_hours = max(4.0, random.gauss(avg_time, 8.0))
            promised_hours = random.choice([24, 48, 72])
            create_delivered_parcel(home_zone, duty_date, delivery_hours, promised_hours, rider_id)
        for _ in range(day_failed):
            reason = reasons[reason_cursor]
            reason_cursor += 1
            create_failed_parcel(home_zone, duty_date, rider_id, reason)

    assert reason_cursor == failed_total, (rider_id, reason_cursor, failed_total)


for _rider in FIXED_RIDERS:
    _breakdown = RD114_REASON_BREAKDOWN if _rider["rider_id"] == "RD-114" else None
    generate_june_rider_data(_rider, reason_breakdown=_breakdown)

for _rider in EXTRA_RIDERS:
    generate_june_rider_data(_rider)


# ---------------------------------------------------------------------------
# M4 demonstration set: PC-77012 plus >= 15 hand-authored addresses spanning
# all three zones, clean matches, spelling variants, landmark-only text, and
# at least two below-threshold addresses for the manual-sorting queue. These
# are booked but deliberately left WITHOUT any scans or zone_assignment row,
# so the live "Run AI Matching" demo in the M4 module has real, unprocessed
# parcels to work on (see the D2 addendum in docs/SPEC_DECISIONS.md).
# ---------------------------------------------------------------------------

# Each address below is deliberately built from k or more of its target
# zone's own cleaned terms and nothing else, where k is the smallest integer
# with sqrt(k / |zone terms|) >= 0.80 -- i.e. the fewest zone terms an
# address can contain (with zero unrelated terms) and still clear the
# auto-assign threshold (k=4 of 5 for Z-MIR, k=6 of 8 for Z-UTT, k=4 of 6 for
# Z-DHN). Spelling-variant entries add one extra misspelled term that does
# NOT match the zone vocabulary, to show the match still succeeds on the
# strength of the other terms.
DEMO_ADDRESSES = [
    {"parcel_id": "PC-77012", "address": PC_77012_ADDRESS, "category": "clean_match", "expected_zone": "Z-MIR"},
    {"parcel_id": "PC-77013", "address": "Uttara, Sector 7, Rajlokkhi, Kuril, Azampur, Jasimuddin", "category": "clean_match", "expected_zone": "Z-UTT"},
    {"parcel_id": "PC-77014", "address": "Dhanmondi, Satmasjid, Kalabagan, Rayerbazar", "category": "clean_match", "expected_zone": "Z-DHN"},
    {"parcel_id": "PC-77015", "address": "Mirpur, Kazipara, Shewrapara, Section, Pallobi", "category": "spelling_variant", "expected_zone": "Z-MIR"},
    {"parcel_id": "PC-77016", "address": "Uttara, Sector 7, Rajlokkhi, Kuril, Azampur, Jasimuddin, School, Uttarah", "category": "spelling_variant", "expected_zone": "Z-UTT"},
    {"parcel_id": "PC-77017", "address": "Dhanmondi, Satmasjid, Kalabagan, Rayerbazar, Hatirpool, Lakes", "category": "spelling_variant", "expected_zone": "Z-DHN"},
    {"parcel_id": "PC-77018", "address": "Shewrapara, Section, Mirpur, Kazipara", "category": "clean_match", "expected_zone": "Z-MIR"},
    {"parcel_id": "PC-77019", "address": "Azampur, Uttara, Sector, Kuril, Rajlokkhi, Airport", "category": "landmark_only", "expected_zone": "Z-UTT"},
    {"parcel_id": "PC-77020", "address": "near college gate, Dhaka", "category": "below_threshold", "expected_zone": None},
    {"parcel_id": "PC-77021", "address": "Rayerbazar, Hatirpool, Dhanmondi, Satmasjid", "category": "clean_match", "expected_zone": "Z-DHN"},
    {"parcel_id": "PC-77022", "address": "Kazipara, Mirpur, Shewrapara, Section", "category": "landmark_only", "expected_zone": "Z-MIR"},
    {"parcel_id": "PC-77023", "address": "Rajlokkhi, Kuril, Uttara, Sector, Azampur, Jasimuddin", "category": "clean_match", "expected_zone": "Z-UTT"},
    {"parcel_id": "PC-77024", "address": "some house near the big road, Dhaka", "category": "below_threshold", "expected_zone": None},
    {"parcel_id": "PC-77025", "address": "Kalabagan, Dhanmondi, Satmasjid, Rayerbazar", "category": "clean_match", "expected_zone": "Z-DHN"},
    {"parcel_id": "PC-77026", "address": "Shewrapara, Mirpur, Section, Kazipara", "category": "clean_match", "expected_zone": "Z-MIR"},
    {"parcel_id": "PC-77027", "address": "Jasimuddin, Uttara, School, Sector, Kuril, Azampur", "category": "landmark_only", "expected_zone": "Z-UTT"},
]

_demo_zone_counts = {"Z-MIR": 0, "Z-UTT": 0, "Z-DHN": 0}
for _entry in DEMO_ADDRESSES:
    if _entry["expected_zone"]:
        _demo_zone_counts[_entry["expected_zone"]] += 1
assert len(DEMO_ADDRESSES) >= 15, len(DEMO_ADDRESSES)
assert all(count >= 1 for count in _demo_zone_counts.values()), _demo_zone_counts
_below_threshold_count = sum(1 for e in DEMO_ADDRESSES if e["category"] == "below_threshold")
assert _below_threshold_count >= 2, _below_threshold_count

for _entry in DEMO_ADDRESSES:
    _terms = clean_terms(_entry["address"])
    _scores = score_against_all_zones(_terms)
    _best_zone_id, _best_score = _scores[0]
    if _entry["category"] == "below_threshold":
        assert _best_score < SIMILARITY_THRESHOLD - SIMILARITY_EPSILON, (_entry["parcel_id"], _scores)
    else:
        assert _best_zone_id == _entry["expected_zone"], (_entry["parcel_id"], _scores)
        assert _best_score >= SIMILARITY_THRESHOLD - SIMILARITY_EPSILON, (_entry["parcel_id"], _scores)
    _entry["computed_score"] = _best_score
    _entry["computed_zone"] = _best_zone_id if _best_score >= SIMILARITY_THRESHOLD - SIMILARITY_EPSILON else ""

    booked_at = datetime.combine(TODAY, datetime.min.time()) + timedelta(hours=random.uniform(7, 10))
    parcels_rows.append({
        "parcel_id": _entry["parcel_id"],
        "booked_at": booked_at.strftime("%Y-%m-%d %H:%M:%S"),
        "promised_hours": 48,
        "delivery_address": _entry["address"],
        "cod_amount": 0.0,
    })
    # Deliberately no scans and no zone_assignments row -- see docstring above.


# ---------------------------------------------------------------------------
# Write CSVs
# ---------------------------------------------------------------------------

def write_csv(filename, fieldnames, rows):
    path = DATA_DIR / filename
    with open(path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)
    print(f"wrote {len(rows):>6} rows -> {path}")


def main():
    # Total volume lands around 8,500 parcels, higher than the "roughly
    # 4,500-5,000" guideline -- because the June rider totals (dictated by
    # the M2 worked examples and the D5 mean-productivity solve) and the
    # July 7-day window totals (dictated by the R2 worked examples) are two
    # independently exact, non-overlapping pools that both have to exist in
    # full for their respective worked examples to reproduce; each pool
    # alone is already close to the guideline's whole range. Correctness of
    # the examined figures takes priority over hitting the approximate
    # volume figure. Generation still completes in under a second either way.
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    write_csv("zones.csv", ["zone_id", "zone_name", "hub", "description"], ZONES)
    write_csv(
        "riders.csv", ["rider_id", "name", "home_zone", "duty_days"],
        [{"rider_id": r["rider_id"], "name": r["name"], "home_zone": r["home_zone"], "duty_days": r["duty_days"]} for r in ALL_RIDERS],
    )
    write_csv(
        "parcels.csv",
        ["parcel_id", "booked_at", "promised_hours", "delivery_address", "cod_amount"],
        parcels_rows,
    )
    write_csv(
        "scans.csv",
        ["scan_id", "parcel_id", "scan_type", "rider_id", "scanned_at", "failure_reason"],
        scans_rows,
    )
    write_csv("deposits.csv", ["rider_id", "deposit_date", "amount"], deposits_rows)
    write_csv(
        "zone_assignments.csv",
        ["parcel_id", "zone_id", "similarity_score", "source", "created_at"],
        zone_assignments_rows,
    )
    write_csv(
        "demo_addresses.csv",
        ["parcel_id", "address", "category", "expected_zone", "computed_zone", "computed_score"],
        [
            {
                "parcel_id": e["parcel_id"], "address": e["address"], "category": e["category"],
                "expected_zone": e["expected_zone"] or "", "computed_zone": e["computed_zone"],
                "computed_score": round(e["computed_score"], 4),
            }
            for e in DEMO_ADDRESSES
        ],
    )

    print()
    print(f"Total parcels: {len(parcels_rows)}")
    print(f"Total scans:   {len(scans_rows)}")
    print(f"Company mean productivity (pi-bar): {MEAN_PRODUCTIVITY:.4f} -> displays 19.5")
    print(f"Coaching threshold (unrounded):      {COACHING_THRESHOLD:.4f} -> displays 13.7")


if __name__ == "__main__":
    main()
