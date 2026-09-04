"""Shared text-cleaning and cosine-similarity logic for M4 address-to-zone matching.

This module is used both by scripts/generate_data.py (to precompute the zone
match for every historical parcel while building the seed data) and by
modules/m4_matching.py (the live M4 module used by the running app). Keeping
the algorithm in one place guarantees the two callers can never drift apart.
"""

import re
from math import sqrt

# §6.2: "generic address words" removed before matching, regardless of position.
GENERIC_ADDRESS_WORDS = {"house", "road", "flat", "floor"}

# §6.2 / worked example: positional stop-words removed. "opposite" must be
# dropped for the §6.3 worked example (PC-77012's address) to clean correctly.
POSITIONAL_STOP_WORDS = {
    "opposite", "near", "beside", "behind", "front",
    "of", "the", "at", "in", "side",
}


def clean_term_list(text):
    """Clean free text into a list of terms used by Eq. (10), keeping every
    occurrence (not deduplicated). The binary matching mode only needs the
    distinct set (see clean_terms below), but the optional TF-IDF upgrade
    needs each term's frequency within the text, which a deduplicated set
    cannot give.

    Tokenisation pipeline, applied in this exact order (see BUILD_PROMPT.md
    §6 for why the order matters -- reversed order would leave "opposite" or
    bare numbers in the term list and break the §6.3 worked example):

    1. lowercase
    2. strip punctuation, split on whitespace
    3. drop pure numbers ("12", "3", "7")
    4. drop generic address words (house, road, flat, floor)
    5. drop positional stop-words (opposite, near, beside, ...)
    """
    lowered = text.lower()
    stripped_of_punctuation = re.sub(r"[^\w\s]", " ", lowered)
    raw_tokens = stripped_of_punctuation.split()

    terms = []
    for token in raw_tokens:
        if token.isdigit():
            continue
        if token in GENERIC_ADDRESS_WORDS:
            continue
        if token in POSITIONAL_STOP_WORDS:
            continue
        terms.append(token)
    return terms


def clean_terms(text):
    """Clean free text into the distinct term SET used by Eq. (10)'s binary
    vectors -- see clean_term_list for the tokenisation pipeline itself.
    Step 6 here is the deduplication binary matching needs that TF-IDF does
    not: 'deduplicate clean_term_list's output into a set'.
    """
    return set(clean_term_list(text))


def binary_cosine_similarity(terms_a, terms_b):
    """Eq. (10): sim(A, C) = (A . C) / (||A|| * ||C||), binary term vectors.

    A . C is the count of terms common to both sets; ||A|| and ||C|| are the
    square roots of the number of distinct terms in each set (binary vectors,
    so a vector's own dot product with itself is just its term count).
    """
    if not terms_a or not terms_b:
        return 0.0
    common_term_count = len(terms_a & terms_b)
    norm_a = sqrt(len(terms_a))
    norm_b = sqrt(len(terms_b))
    return common_term_count / (norm_a * norm_b)
