"""M4 -- AI Address-to-Zone Matching.

Implements Eq. (10) (binary cosine similarity, the default) and its
optional TF-IDF upgrade, plus auto-assignment, batch matching and
dispatcher overrides. This is the one module allowed to write anything: it
INSERTs into zone_assignments only -- never UPDATE, never DELETE (decision
D2). It never writes to parcels, scans, riders, zones or deposits.
"""

from datetime import datetime
from math import log, sqrt

from modules.text_similarity import binary_cosine_similarity, clean_term_list, clean_terms

SIMILARITY_THRESHOLD = 0.80
# Floating-point sqrt arithmetic can land a "true" 0.80 score a hair below
# 0.80 (e.g. 0.7999999999999998); every threshold comparison below tolerates
# that. scripts/generate_data.py uses this same constant.
SIMILARITY_EPSILON = 1e-9


def _get_zones(connection):
    return connection.execute("SELECT zone_id, zone_name, description FROM zones ORDER BY zone_id").fetchall()


def _binary_scores(address_text, zones):
    address_terms = clean_terms(address_text)
    scored = []
    for zone in zones:
        zone_terms = clean_terms(zone["description"])
        score = binary_cosine_similarity(address_terms, zone_terms)  # Eq. (10)
        scored.append({"zone_id": zone["zone_id"], "zone_name": zone["zone_name"], "score": score})
    return scored


def _term_frequencies(term_list):
    """tf_t for every distinct term in term_list."""
    frequencies = {}
    for term in term_list:
        frequencies[term] = frequencies.get(term, 0) + 1
    return frequencies


def _document_frequencies(zone_term_lists):
    """df_t: the number of zone descriptions containing term t, for every
    term appearing in at least one zone description."""
    document_frequencies = {}
    for term_list in zone_term_lists:
        for term in set(term_list):
            document_frequencies[term] = document_frequencies.get(term, 0) + 1
    return document_frequencies


def _tfidf_vector(term_list, document_frequencies, total_documents):
    """w_t = tf_t * log(N / df_t) for every distinct term in term_list
    (Section 6.2's optional upgrade). A term that never appears in any zone
    description has no df_t entry; treat it as df_t = 1 so it gets a large
    but finite weight instead of causing a division by zero."""
    term_frequencies = _term_frequencies(term_list)
    vector = {}
    for term, tf in term_frequencies.items():
        df = document_frequencies.get(term, 1)
        vector[term] = tf * log(total_documents / df)
    return vector


def _tfidf_cosine_similarity(vector_a, vector_b):
    common_terms = set(vector_a) & set(vector_b)
    dot_product = sum(vector_a[term] * vector_b[term] for term in common_terms)
    norm_a = sqrt(sum(weight * weight for weight in vector_a.values()))
    norm_b = sqrt(sum(weight * weight for weight in vector_b.values()))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot_product / (norm_a * norm_b)


def _tfidf_scores(address_text, zones):
    address_term_list = clean_term_list(address_text)
    zone_term_lists = {zone["zone_id"]: clean_term_list(zone["description"]) for zone in zones}
    total_documents = len(zones)  # N: total number of zone descriptions
    document_frequencies = _document_frequencies(zone_term_lists.values())

    address_vector = _tfidf_vector(address_term_list, document_frequencies, total_documents)

    scored = []
    for zone in zones:
        zone_vector = _tfidf_vector(zone_term_lists[zone["zone_id"]], document_frequencies, total_documents)
        score = _tfidf_cosine_similarity(address_vector, zone_vector)
        scored.append({"zone_id": zone["zone_id"], "zone_name": zone["zone_name"], "score": score})
    return scored


def meets_threshold(score):
    """Whether score clears the 0.80 auto-assign threshold, tolerating the
    same floating-point sqrt noise SIMILARITY_EPSILON exists for. Templates
    must call this instead of comparing a raw score >= 0.80 themselves --
    an exact-0.80 case (like PC-77012's) can compute as 0.7999999999999998,
    which a plain >= comparison would wrongly reject.
    """
    return score >= SIMILARITY_THRESHOLD - SIMILARITY_EPSILON


def score_parcel_against_zones(connection, address_text, use_tfidf=False):
    """Score address_text against every zone, ranked best first.

    Binary mode (Eq. 10) is the default; use_tfidf switches to the Section
    6.2 TF-IDF upgrade. Returns a list of {"zone_id", "zone_name", "score",
    "meets_threshold"}.
    """
    zones = _get_zones(connection)
    scored = _tfidf_scores(address_text, zones) if use_tfidf else _binary_scores(address_text, zones)
    scored.sort(key=lambda entry: entry["score"], reverse=True)
    for entry in scored:
        entry["meets_threshold"] = meets_threshold(entry["score"])
    return scored


def resolve_auto_assignment(ranked_scores):
    """Decide the auto-assign outcome from a ranked (best-first) score list.

    The top zone wins if its score clears the 0.80 threshold. If the top two
    zones are tied at or above the threshold, the parcel goes to the manual
    queue instead of picking one arbitrarily (BUILD_PROMPT.md's M4 section).
    Returns (zone_id, best_score); zone_id is None for the manual queue.
    """
    if not ranked_scores:
        return None, 0.0

    best = ranked_scores[0]
    if not meets_threshold(best["score"]):
        return None, best["score"]

    if len(ranked_scores) > 1:
        second = ranked_scores[1]
        tied = abs(best["score"] - second["score"]) < SIMILARITY_EPSILON
        if tied and meets_threshold(second["score"]):
            return None, best["score"]

    return best["zone_id"], best["score"]


def get_current_assignment(connection, parcel_id):
    """The current zone_assignments row for parcel_id -- the row with the
    highest id (decision D2) -- or None if it has never been matched."""
    return connection.execute(
        """
        SELECT za.zone_id, za.similarity_score, za.source, za.created_at, z.zone_name
        FROM zone_assignments za
        LEFT JOIN zones z ON z.zone_id = za.zone_id
        WHERE za.parcel_id = ?
        ORDER BY za.id DESC
        LIMIT 1
        """,
        (parcel_id,),
    ).fetchone()


def record_auto_assignment(connection, parcel_id, use_tfidf=False):
    """Score parcel_id's address against every zone and INSERT one
    zone_assignments row: the winning zone if it clears the threshold
    (and isn't tied with a second zone at/above threshold), else NULL for
    the manual sorting queue. INSERT-only -- see decision D2.

    Returns (ranked_scores, assigned_zone_id).
    """
    parcel = connection.execute(
        "SELECT delivery_address FROM parcels WHERE parcel_id = ?", (parcel_id,)
    ).fetchone()
    if parcel is None:
        return [], None

    ranked_scores = score_parcel_against_zones(connection, parcel["delivery_address"], use_tfidf)
    zone_id, best_score = resolve_auto_assignment(ranked_scores)

    created_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    connection.execute(
        "INSERT INTO zone_assignments (parcel_id, zone_id, similarity_score, source, created_at) "
        "VALUES (?, ?, ?, 'auto', ?)",
        (parcel_id, zone_id, best_score, created_at),
    )
    connection.commit()

    return ranked_scores, zone_id


def record_manual_override(connection, parcel_id, chosen_zone_id):
    """Dispatcher override (Section 6.1): INSERT a new 'manual'
    zone_assignments row for parcel_id, choosing chosen_zone_id regardless
    of its similarity score. The previous row is never touched -- decision
    D2's audit trail is exactly this: every past assignment stays in place.
    """
    parcel = connection.execute(
        "SELECT delivery_address FROM parcels WHERE parcel_id = ?", (parcel_id,)
    ).fetchone()
    zone = connection.execute(
        "SELECT description FROM zones WHERE zone_id = ?", (chosen_zone_id,)
    ).fetchone()
    score = binary_cosine_similarity(clean_terms(parcel["delivery_address"]), clean_terms(zone["description"]))

    created_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    connection.execute(
        "INSERT INTO zone_assignments (parcel_id, zone_id, similarity_score, source, created_at) "
        "VALUES (?, ?, ?, 'manual', ?)",
        (parcel_id, chosen_zone_id, score, created_at),
    )
    connection.commit()

    return score


def get_unmatched_parcels(connection, limit=50):
    """Parcels with no zone_assignments row at all -- candidates for the M4
    demonstration form and for run_batch_matching."""
    query = """
        SELECT p.parcel_id, p.delivery_address
        FROM parcels p
        WHERE NOT EXISTS (SELECT 1 FROM zone_assignments za WHERE za.parcel_id = p.parcel_id)
        ORDER BY p.parcel_id
        LIMIT ?
    """
    return connection.execute(query, (limit,)).fetchall()


def run_batch_matching(connection, use_tfidf=False):
    """Auto-match every parcel that has no zone_assignments row yet
    (Section 6.1: "the dispatcher's manual-sorting queue" is populated by
    running this over newly-booked, unassigned parcels).

    Returns {"processed", "auto_assigned", "manual_queue"}.
    """
    unmatched = get_unmatched_parcels(connection, limit=100000)

    auto_assigned = 0
    manual_queue = 0
    for row in unmatched:
        _, zone_id = record_auto_assignment(connection, row["parcel_id"], use_tfidf)
        if zone_id:
            auto_assigned += 1
        else:
            manual_queue += 1

    return {"processed": len(unmatched), "auto_assigned": auto_assigned, "manual_queue": manual_queue}


def get_zone_assignment_log(connection, on_date):
    """R5: every parcel booked on on_date, with its current assignment
    status (Section 7.5 of the PDF)."""
    query = """
        SELECT p.parcel_id, p.delivery_address, za.zone_id, za.similarity_score, za.source
        FROM parcels p
        LEFT JOIN zone_assignments za
          ON za.parcel_id = p.parcel_id
         AND za.id = (SELECT MAX(id) FROM zone_assignments WHERE parcel_id = p.parcel_id)
        WHERE date(p.booked_at) = ?
        ORDER BY p.parcel_id
    """
    rows = connection.execute(query, (on_date,)).fetchall()
    zone_names = {z["zone_id"]: z["zone_name"] for z in _get_zones(connection)}

    entries = []
    auto_assigned_count = 0
    manual_queue_count = 0
    dispatcher_override_count = 0

    for row in rows:
        if row["source"] is None:
            status = "Not yet matched"
        elif row["source"] == "manual":
            status = "Dispatcher override"
            dispatcher_override_count += 1
        elif row["zone_id"] is not None:
            status = "Auto-assigned"
            auto_assigned_count += 1
        else:
            status = "Manual sorting queue"
            manual_queue_count += 1

        entries.append({
            "parcel_id": row["parcel_id"],
            "address_prefix": row["delivery_address"][:40],
            "zone_id": row["zone_id"],
            "zone_name": zone_names.get(row["zone_id"]),
            "similarity_score": row["similarity_score"],
            "status": status,
        })

    return {
        "date": on_date,
        "entries": entries,
        "booked_count": len(entries),
        "auto_assigned_count": auto_assigned_count,
        "manual_queue_count": manual_queue_count,
        "dispatcher_override_count": dispatcher_override_count,
    }
