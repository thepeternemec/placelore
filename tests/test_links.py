"""Tests for the wiki-place <-> Google-id <-> photo chain."""

from __future__ import annotations

import json
import sqlite3
import unittest

from placeswiki.links import (
    LinkError,
    add_link,
    check_integrity,
    export_links,
    import_links,
    link_report,
    remove_link,
    set_primary,
    validate_google_id,
)
from placeswiki.schema import ensure_schema

GOOGLE_A = "ChIJrTLr-GyuEmsRBfy61i59si0"
GOOGLE_B = "ChIJSecondCandidateForSamePlace000"
GOOGLE_C = "ChIJArchOfTitus000000000000000000"


class Base(unittest.TestCase):
    def setUp(self):
        self.conn = sqlite3.connect(":memory:")
        self.conn.row_factory = sqlite3.Row
        ensure_schema(self.conn)
        for place_id, name, lat, lng in (
            ("wc:enwiki:1", "Colosseum", 41.8902, 12.4922),
            ("wc:enwiki:2", "Arch of Titus", 41.8907, 12.4886),
        ):
            self.conn.execute(
                "INSERT INTO places (id, name, lat, lng, types) VALUES (?, ?, ?, ?, '[]')",
                (place_id, name, lat, lng),
            )
        self.conn.execute(
            "INSERT INTO place_photos (id, place_id, name, url) VALUES"
            " ('commons:X.jpg', 'wc:enwiki:1', 'places/wc:enwiki:1/photos/x', 'https://u/x.jpg')"
        )
        self.conn.commit()


class TestValidation(unittest.TestCase):
    def test_accepts_google_shaped_ids(self):
        self.assertEqual(validate_google_id("  ChIJrTLr-GyuEmsRBfy61i59si0 "), GOOGLE_A)

    def test_rejects_empty_and_garbage(self):
        for bad in ("", "   ", None, "short", "has spaces here", "quote'inside"):
            with self.assertRaises(LinkError):
                validate_google_id(bad)


class TestLinks(Base):
    def test_first_link_becomes_primary_and_syncs_cache(self):
        self.assertTrue(add_link(self.conn, "wc:enwiki:1", GOOGLE_A, method="test"))
        row = self.conn.execute(
            "SELECT google_place_id FROM places WHERE id='wc:enwiki:1'"
        ).fetchone()
        self.assertEqual(row["google_place_id"], GOOGLE_A)

    def test_second_link_does_not_steal_primary(self):
        add_link(self.conn, "wc:enwiki:1", GOOGLE_A, method="test")
        self.assertFalse(add_link(self.conn, "wc:enwiki:1", GOOGLE_B, method="test"))
        primaries = self.conn.execute(
            "SELECT google_place_id FROM place_links WHERE place_id='wc:enwiki:1' AND is_primary=1"
        ).fetchall()
        self.assertEqual([r[0] for r in primaries], [GOOGLE_A])

    def test_set_primary_switches_and_resyncs(self):
        add_link(self.conn, "wc:enwiki:1", GOOGLE_A, method="test")
        add_link(self.conn, "wc:enwiki:1", GOOGLE_B, method="test")
        set_primary(self.conn, "wc:enwiki:1", GOOGLE_B)
        row = self.conn.execute(
            "SELECT google_place_id FROM places WHERE id='wc:enwiki:1'"
        ).fetchone()
        self.assertEqual(row["google_place_id"], GOOGLE_B)
        self.assertEqual(check_integrity(self.conn), [])

    def test_remove_primary_promotes_the_next_candidate(self):
        add_link(self.conn, "wc:enwiki:1", GOOGLE_A, method="test", confidence=0.4)
        add_link(self.conn, "wc:enwiki:1", GOOGLE_B, method="test", confidence=0.9)
        remove_link(self.conn, "wc:enwiki:1", GOOGLE_A)
        row = self.conn.execute(
            "SELECT google_place_id FROM places WHERE id='wc:enwiki:1'"
        ).fetchone()
        self.assertEqual(row["google_place_id"], GOOGLE_B)
        self.assertEqual(check_integrity(self.conn), [])

    def test_remove_last_link_clears_the_cache(self):
        add_link(self.conn, "wc:enwiki:1", GOOGLE_A, method="test", confidence=0.8)
        remove_link(self.conn, "wc:enwiki:1", GOOGLE_A)
        row = self.conn.execute(
            "SELECT google_place_id, match_confidence FROM places WHERE id='wc:enwiki:1'"
        ).fetchone()
        self.assertIsNone(row["google_place_id"])
        self.assertIsNone(row["match_confidence"])

    def test_removing_unknown_link_raises(self):
        with self.assertRaises(LinkError):
            remove_link(self.conn, "wc:enwiki:1", GOOGLE_A)

    def test_duplicate_add_updates_confidence_only(self):
        add_link(self.conn, "wc:enwiki:1", GOOGLE_A, method="test", confidence=0.5)
        add_link(self.conn, "wc:enwiki:1", GOOGLE_A, method="test", confidence=0.9)
        rows = self.conn.execute("SELECT * FROM place_links").fetchall()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["confidence"], 0.9)

    def test_matcher_evidence_round_trips(self):
        add_link(
            self.conn,
            "wc:enwiki:1",
            GOOGLE_A,
            method="searchText",
            confidence=0.8,
            evidence={"query": "Colosseum", "distance_m": 12.5},
        )
        evidence = json.loads(
            self.conn.execute("SELECT evidence FROM place_links").fetchone()["evidence"]
        )
        self.assertEqual(evidence["distance_m"], 12.5)


class TestImport(Base):
    def test_import_by_id_and_title(self):
        rows = [
            {"place_id": "wc:enwiki:1", "google_place_id": GOOGLE_A},
            {"title": "Arch of Titus", "google_place_id": GOOGLE_C},
        ]
        summary = import_links(self.conn, rows)
        self.assertEqual(summary["added"], 2)
        self.assertEqual(summary["errors"], [])
        self.assertEqual(link_report(self.conn)["places_linked"], 2)

    def test_import_reports_bad_rows_without_aborting(self):
        rows = [
            {"place_id": "wc:enwiki:1", "google_place_id": GOOGLE_A},
            {"place_id": "wc:missing", "google_place_id": GOOGLE_C},
            {"place_id": "wc:enwiki:2", "google_place_id": "bad id"},
            {"title": "Arch of Titus"},
        ]
        summary = import_links(self.conn, rows)
        self.assertEqual(summary["added"], 1)
        self.assertEqual(len(summary["errors"]), 3)

    def test_dry_run_changes_nothing(self):
        summary = import_links(
            self.conn, [{"place_id": "wc:enwiki:1", "google_place_id": GOOGLE_A}], dry_run=True
        )
        self.assertEqual(summary["added"], 1)
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM place_links").fetchone()[0], 0)


class TestIntegrity(Base):
    def test_clean_after_link(self):
        add_link(self.conn, "wc:enwiki:1", GOOGLE_A, method="test")
        self.assertEqual(check_integrity(self.conn), [])

    def test_detects_cache_divergence(self):
        add_link(self.conn, "wc:enwiki:1", GOOGLE_A, method="test")
        self.conn.execute(
            "UPDATE places SET google_place_id='ChIJTampered000000000000000000000' WHERE id='wc:enwiki:1'"
        )
        problems = check_integrity(self.conn)
        self.assertTrue(any("diverges" in message for _, message in problems))

    def test_warns_on_non_chij_prefix(self):
        add_link(self.conn, "wc:enwiki:1", "AbCdEfGhIjKlMnOpQrSt", method="test")
        problems = check_integrity(self.conn)
        self.assertTrue(any("ChIJ" in message for _, message in problems))


class TestExport(Base):
    def test_chain_includes_photos(self):
        add_link(self.conn, "wc:enwiki:1", GOOGLE_A, method="test", confidence=0.9)
        payload = export_links(self.conn)
        self.assertEqual(len(payload["linked"]), 1)
        entry = payload["linked"][0]
        self.assertEqual(entry["google_place_id"], GOOGLE_A)
        self.assertEqual(entry["photo_count"], 1)
        self.assertEqual(entry["photos"][0]["url"], "https://u/x.jpg")
        self.assertTrue(any(u["wiki_place_id"] == "wc:enwiki:2" for u in payload["unlinked"]))

    def test_linked_only_omits_unlinked(self):
        add_link(self.conn, "wc:enwiki:1", GOOGLE_A, method="test")
        payload = export_links(self.conn, include_unlinked=False)
        self.assertNotIn("unlinked", payload)

    def test_report_counts_photos_behind_links(self):
        add_link(self.conn, "wc:enwiki:1", GOOGLE_A, method="test")
        report = link_report(self.conn)
        self.assertEqual(report["photos"], 1)
        self.assertEqual(report["photos_linked"], 1)
        self.assertEqual(report["cache_in_sync"], 1)


if __name__ == "__main__":
    unittest.main()
