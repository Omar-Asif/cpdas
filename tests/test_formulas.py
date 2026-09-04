"""Unit tests for the CPDAS formula modules.

Each test builds a tiny in-memory SQLite database (from schema.sql) with a
handful of hand-written rows and checks the module's output by hand against
the PDF's own worked examples -- independent of scripts/generate_data.py's
seeded cpdas.db, so these tests still catch a regression even if the seed
data is ever regenerated differently.

Run with: python -m unittest tests.test_formulas -v  (from the project root)
"""

import sqlite3
import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from modules import m1_delivery, m2_rider, m3_cod, m4_matching
from modules.formatting import round_half_up
from modules.text_similarity import binary_cosine_similarity, clean_terms


def make_test_connection():
    """An empty in-memory database built from schema.sql."""
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    connection.executescript((PROJECT_ROOT / "schema.sql").read_text(encoding="utf-8"))
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


class TestM1DeliveryPerformance(unittest.TestCase):
    """Eq. (1)-(4): hand-built parcels with known delivery times, verified
    against arithmetic worked by hand rather than the seeded database."""

    def setUp(self):
        self.connection = make_test_connection()
        self.connection.execute(
            "INSERT INTO zones (zone_id, zone_name, hub, description) VALUES "
            "('Z-MIR', 'Mirpur', 'Mirpur Hub', 'Mirpur, Pallabi, Kazipara, Shewrapara, Section')"
        )
        self.connection.execute(
            "INSERT INTO riders (rider_id, name, home_zone, duty_days) VALUES ('RD-1', 'Test Rider', 'Z-MIR', 20)"
        )
        # T_p = delivered_at - booked_at (Eq. 2).
        self._insert_delivered("PC-1", "2026-01-01 08:00:00", "2026-01-01 20:00:00", promised_hours=48)  # T_p=12h, on-time
        self._insert_delivered("PC-2", "2025-12-30 08:00:00", "2026-01-01 08:00:00", promised_hours=24)  # T_p=48h, late, delivered on the query date
        self._insert_delivered("PC-3", "2026-01-01 08:00:00", "2026-01-01 14:00:00", promised_hours=48)  # T_p=6h, on-time
        self._insert_failed("PC-4", "2026-01-01 09:00:00")
        for parcel_id in ["PC-1", "PC-2", "PC-3", "PC-4"]:
            self._assign_zone(parcel_id, "Z-MIR")
        self.connection.commit()

    def _insert_delivered(self, parcel_id, booked_at, delivered_at, promised_hours):
        self.connection.execute(
            "INSERT INTO parcels (parcel_id, booked_at, promised_hours, delivery_address, cod_amount) "
            "VALUES (?, ?, ?, 'test address', 0)",
            (parcel_id, booked_at, promised_hours),
        )
        self.connection.execute(
            "INSERT INTO scans (parcel_id, scan_type, rider_id, scanned_at, failure_reason) "
            "VALUES (?, 'hub_out', 'RD-1', ?, NULL)",
            (parcel_id, booked_at),
        )
        self.connection.execute(
            "INSERT INTO scans (parcel_id, scan_type, rider_id, scanned_at, failure_reason) "
            "VALUES (?, 'delivered', 'RD-1', ?, NULL)",
            (parcel_id, delivered_at),
        )

    def _insert_failed(self, parcel_id, scanned_at):
        self.connection.execute(
            "INSERT INTO parcels (parcel_id, booked_at, promised_hours, delivery_address, cod_amount) "
            "VALUES (?, ?, 48, 'test address', 0)",
            (parcel_id, scanned_at),
        )
        self.connection.execute(
            "INSERT INTO scans (parcel_id, scan_type, rider_id, scanned_at, failure_reason) "
            "VALUES (?, 'failed_attempt', 'RD-1', ?, 'customer unreachable')",
            (parcel_id, scanned_at),
        )

    def _assign_zone(self, parcel_id, zone_id):
        self.connection.execute(
            "INSERT INTO zone_assignments (parcel_id, zone_id, similarity_score, source, created_at) "
            "VALUES (?, ?, 1.0, 'auto', '2026-01-01 00:00:00')",
            (parcel_id, zone_id),
        )

    def tearDown(self):
        self.connection.close()

    def test_eq1_success_rate(self):
        result = m1_delivery.get_zone_performance(self.connection, "Z-MIR", "2026-01-01")
        self.assertEqual(result["n_attempted"], 4)   # 3 delivered + 1 failed (decision D3)
        self.assertEqual(result["n_delivered"], 3)
        self.assertEqual(result["n_failed"], 1)
        self.assertAlmostEqual(result["success_pct"], 3 / 4 * 100)

    def test_eq2_and_eq3_on_time_count(self):
        result = m1_delivery.get_zone_performance(self.connection, "Z-MIR", "2026-01-01")
        # PC-1: T_p=12h <= 48h promised -> on-time. PC-2: T_p=48h > 24h promised -> late.
        # PC-3: T_p=6h <= 48h promised -> on-time. 2 of 3 delivered parcels are on-time.
        self.assertEqual(result["on_time_count"], 2)
        self.assertAlmostEqual(result["on_time_pct"], 2 / 3 * 100)

    def test_eq4_average_delivery_time(self):
        result = m1_delivery.get_zone_performance(self.connection, "Z-MIR", "2026-01-01")
        self.assertAlmostEqual(result["avg_delivery_hours"], (12 + 48 + 6) / 3)

    def test_operations_review_flag_needs_three_consecutive_days(self):
        # Only one day of data exists (2026-01-01); Section 3.3 requires
        # three consecutive days below 85% before the flag fires.
        result = m1_delivery.get_zone_performance(self.connection, "Z-MIR", "2026-01-01")
        self.assertFalse(result["operations_review_flag"])


class TestM2RiderProductivity(unittest.TestCase):
    """Eq. (5)-(6), reproducing the Section 4.3 worked example exactly:
    508 delivered / 24 duty days, 52 failed attempts."""

    def setUp(self):
        self.connection = make_test_connection()
        self.connection.execute(
            "INSERT INTO zones (zone_id, zone_name, hub, description) VALUES ('Z-MIR', 'Mirpur', 'Mirpur Hub', 'test')"
        )
        self.connection.execute(
            "INSERT INTO riders (rider_id, name, home_zone, duty_days) VALUES ('RD-114', 'Sumon Mia', 'Z-MIR', 24)"
        )
        for i in range(508):
            self._insert_scan(f"PCD-{i}", "delivered", None)
        for i in range(52):
            reason = "customer unreachable" if i < 31 else ("address not found" if i < 45 else "other reason")
            self._insert_scan(f"PCF-{i}", "failed_attempt", reason)
        self.connection.commit()

    def _insert_scan(self, parcel_id, scan_type, reason):
        self.connection.execute(
            "INSERT INTO parcels (parcel_id, booked_at, promised_hours, delivery_address, cod_amount) "
            "VALUES (?, '2026-06-01 08:00:00', 48, 'test', 0)",
            (parcel_id,),
        )
        self.connection.execute(
            "INSERT INTO scans (parcel_id, scan_type, rider_id, scanned_at, failure_reason) "
            "VALUES (?, ?, 'RD-114', '2026-06-01 09:00:00', ?)",
            (parcel_id, scan_type, reason),
        )

    def tearDown(self):
        self.connection.close()

    def test_eq5_productivity(self):
        result = m2_rider.get_rider_productivity(self.connection, "RD-114", "2026-06")
        self.assertEqual(result["n_delivered"], 508)
        self.assertAlmostEqual(result["pi_r"], 508 / 24)

    def test_eq6_fail_rate(self):
        result = m2_rider.get_rider_productivity(self.connection, "RD-114", "2026-06")
        self.assertEqual(result["n_failed"], 52)
        self.assertAlmostEqual(result["fail_rate_pct"], 52 / (508 + 52) * 100)

    def test_failure_reason_breakdown(self):
        breakdown = {row["reason"]: row["count"] for row in m2_rider.get_failure_reason_breakdown(
            self.connection, "RD-114", "2026-06"
        )}
        self.assertEqual(breakdown["customer unreachable"], 31)
        self.assertEqual(breakdown["address not found"], 14)
        self.assertEqual(breakdown["other reason"], 7)


class TestM3CodReconciliation(unittest.TestCase):
    """Eq. (7)-(9), reproducing the Section 5.3 worked example: RD-114
    fully reconciled, RD-131 short by BDT 1,000."""

    def setUp(self):
        self.connection = make_test_connection()
        self.connection.execute(
            "INSERT INTO zones (zone_id, zone_name, hub, description) VALUES ('Z-MIR', 'Mirpur', 'Mirpur Hub', 'test')"
        )
        self.connection.execute(
            "INSERT INTO riders (rider_id, name, home_zone, duty_days) VALUES ('RD-114', 'Sumon Mia', 'Z-MIR', 24)"
        )
        self.connection.execute(
            "INSERT INTO riders (rider_id, name, home_zone, duty_days) VALUES ('RD-131', 'Liton Sarker', 'Z-MIR', 23)"
        )
        self._deliver_with_cod("PC-A", "RD-114", 38450.0)
        self.connection.execute(
            "INSERT INTO deposits (rider_id, deposit_date, amount) VALUES ('RD-114', '2026-07-08', 38450.0)"
        )
        self._deliver_with_cod("PC-B", "RD-131", 27300.0)
        self.connection.execute(
            "INSERT INTO deposits (rider_id, deposit_date, amount) VALUES ('RD-131', '2026-07-08', 26300.0)"
        )
        self.connection.commit()

    def _deliver_with_cod(self, parcel_id, rider_id, cod_amount):
        self.connection.execute(
            "INSERT INTO parcels (parcel_id, booked_at, promised_hours, delivery_address, cod_amount) "
            "VALUES (?, '2026-07-08 08:00:00', 48, 'test', ?)",
            (parcel_id, cod_amount),
        )
        self.connection.execute(
            "INSERT INTO scans (parcel_id, scan_type, rider_id, scanned_at, failure_reason) "
            "VALUES (?, 'delivered', ?, '2026-07-08 12:00:00', NULL)",
            (parcel_id, rider_id),
        )

    def tearDown(self):
        self.connection.close()

    def test_eq7_and_eq8_reconciled(self):
        result = m3_cod.get_rider_cod_reconciliation(self.connection, "RD-114", "2026-07-08")
        self.assertAlmostEqual(result["collected"], 38450.0)
        self.assertAlmostEqual(result["deposited"], 38450.0)
        self.assertAlmostEqual(result["delta"], 0.0)
        self.assertEqual(result["status"], "Reconciled")

    def test_eq7_and_eq8_shortage(self):
        result = m3_cod.get_rider_cod_reconciliation(self.connection, "RD-131", "2026-07-08")
        self.assertAlmostEqual(result["collected"], 27300.0)
        self.assertAlmostEqual(result["deposited"], 26300.0)
        self.assertAlmostEqual(result["delta"], 1000.0)
        self.assertTrue(result["status"].startswith("Shortage"))

    def test_eq9_shortage_rate_and_escalation(self):
        rate, escalation = m3_cod.get_monthly_shortage_rate(self.connection, "RD-131", "2026-07")
        self.assertAlmostEqual(rate, 1000 / 27300 * 100)
        self.assertTrue(escalation)  # exceeds the 0.5% threshold

    def test_eq9_no_escalation_when_reconciled(self):
        rate, escalation = m3_cod.get_monthly_shortage_rate(self.connection, "RD-114", "2026-07")
        self.assertAlmostEqual(rate, 0.0)
        self.assertFalse(escalation)


class TestM4Matching(unittest.TestCase):
    """Eq. (10), reproducing the Section 6.3 worked example exactly."""

    def test_eq10_worked_example(self):
        address_terms = clean_terms("House 12, Road 3, Section 7, Pallabi, Mirpur, opposite Kazipara school")
        zone_terms = clean_terms("Mirpur, Pallabi, Kazipara, Shewrapara, Section 1-14")
        self.assertEqual(address_terms, {"section", "pallabi", "mirpur", "kazipara", "school"})
        self.assertEqual(zone_terms, {"mirpur", "pallabi", "kazipara", "shewrapara", "section"})
        self.assertAlmostEqual(binary_cosine_similarity(address_terms, zone_terms), 0.80, places=6)

    def test_meets_threshold_tolerates_floating_point_noise(self):
        # sqrt(5)*sqrt(5) can land a true 0.80 a hair below in floating point.
        self.assertTrue(m4_matching.meets_threshold(0.7999999999999998))
        self.assertFalse(m4_matching.meets_threshold(0.79))

    def test_tokeniser_strips_generic_and_positional_words_and_numbers(self):
        terms = clean_terms("House 5, Road 2, near the school, opposite Flat 3")
        for stripped in ["house", "road", "flat", "near", "the", "opposite", "5", "2", "3"]:
            self.assertNotIn(stripped, terms)
        self.assertIn("school", terms)

    def test_resolve_auto_assignment_ties_at_threshold_go_to_manual_queue(self):
        tied_scores = [
            {"zone_id": "Z-A", "zone_name": "A", "score": 0.85},
            {"zone_id": "Z-B", "zone_name": "B", "score": 0.85},
        ]
        zone_id, score = m4_matching.resolve_auto_assignment(tied_scores)
        self.assertIsNone(zone_id)
        self.assertAlmostEqual(score, 0.85)

    def test_resolve_auto_assignment_below_threshold_is_manual_queue(self):
        scores = [{"zone_id": "Z-A", "zone_name": "A", "score": 0.5}]
        zone_id, _ = m4_matching.resolve_auto_assignment(scores)
        self.assertIsNone(zone_id)


class TestFormatting(unittest.TestCase):
    """Decision D10: every display value rounds half up, not Python's
    default round-half-to-even."""

    def test_round_half_up_matches_coaching_threshold_worked_example(self):
        # 0.7 x 19.5 = 13.65 -> displays as 13.7 per the PDF's R3 footer.
        self.assertEqual(round_half_up(13.65, 1), 13.7)

    def test_round_half_up_normalises_negative_zero(self):
        rounded = round_half_up(-0.001, 0)
        self.assertEqual(rounded, 0.0)
        self.assertFalse(str(rounded).startswith("-"))


if __name__ == "__main__":
    unittest.main()
