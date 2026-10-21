"""Tests for the worldwide bulk pipeline (no network)."""

from __future__ import annotations

import json
import sqlite3
import unittest
import urllib.error
from email.message import Message

from wikicrawl.bulk import enrich, ensure_wd_schema, pending, stage, status
from wikicrawl.schema import ensure_schema
from wikicrawl.wikidata import (
    SparqlClient,
    SparqlError,
    commons_file,
    enwiki_title,
    heritage_query,
    parse_row,
    qid,
)

SAMPLE_ROWS = [
    {
        "item": "http://www.wikidata.org/entity/Q1000",
        "label": "Grad Snežnik",
        "lat": "45.6012",
        "lon": "14.3821",
        "article": "https://en.wikipedia.org/wiki/Sne%C5%BEnik_Castle",
        "image": "http://commons.wikimedia.org/wiki/Special:FilePath/Grad%20Sne%C5%BEnik.jpg",
        "category": "Grad Snežnik",
        "heritage": "http://www.wikidata.org/entity/Q18363639",
        "country": "http://www.wikidata.org/entity/Q215",
    },
    # same item, second heritage designation -> must merge
    {
        "item": "http://www.wikidata.org/entity/Q1000",
        "label": "Grad Snežnik",
        "lat": "45.6012",
        "lon": "14.3821",
        "article": "https://en.wikipedia.org/wiki/Sne%C5%BEnik_Castle",
        "image": "http://commons.wikimedia.org/wiki/Special:FilePath/Grad%20Sne%C5%BEnik.jpg",
        "category": "Grad Snežnik",
        "heritage": "http://www.wikidata.org/entity/Q12794452",
        "country": "http://www.wikidata.org/entity/Q215",
    },
    {
        "item": "http://www.wikidata.org/entity/Q2000",
        "label": "Some church",
        "lat": "46.0",
        "lon": "14.5",
        "heritage": "http://www.wikidata.org/entity/Q18363639",
        "country": "http://www.wikidata.org/entity/Q215",
    },
]


class TestQuery(unittest.TestCase):
    def test_query_selects_heritage_with_coordinates(self):
        text = heritage_query(limit=100, offset=200)
        for token in ("P1435", "P625", "LIMIT 100", "OFFSET 200", "PREFIX wdt:"):
            self.assertIn(token, text)

    def test_country_scope_is_injected_as_qid(self):
        text = heritage_query(country="Q215")
        self.assertIn("wd:Q215", text)

    def test_no_country_means_worldwide(self):
        self.assertNotIn("wd:Q", heritage_query())


class TestParsing(unittest.TestCase):
    def test_qid_extraction(self):
        self.assertEqual(qid("http://www.wikidata.org/entity/Q42"), "Q42")
        self.assertEqual(qid(""), "")

    def test_enwiki_title_is_decoded(self):
        self.assertEqual(
            enwiki_title("https://en.wikipedia.org/wiki/Sne%C5%BEnik_Castle"), "Snežnik Castle"
        )
        self.assertEqual(enwiki_title(""), "")

    def test_commons_file_normalisation(self):
        self.assertEqual(
            commons_file(
                "http://commons.wikimedia.org/wiki/Special:FilePath/Grad%20Sne%C5%BEnik.jpg"
            ),
            "File:Grad Snežnik.jpg",
        )
        self.assertEqual(commons_file(""), "")

    def test_parse_row(self):
        record = parse_row(SAMPLE_ROWS[0])
        self.assertEqual(record["qid"], "Q1000")
        self.assertAlmostEqual(record["lat"], 45.6012)
        self.assertEqual(record["enwiki_title"], "Snežnik Castle")
        self.assertEqual(record["image_file"], "File:Grad Snežnik.jpg")
        self.assertEqual(record["country"], "Q215")


class TestSparqlClient(unittest.TestCase):
    def test_returns_plain_rows(self):
        payload = {"results": {"bindings": [{"item": {"value": "Q1"}, "lat": {"value": "1.0"}}]}}
        client = SparqlClient(send=lambda query: payload)
        self.assertEqual(client.query("SELECT"), [{"item": "Q1", "lat": "1.0"}])
        self.assertEqual(client.requests, 1)

    def test_retries_after_429(self):
        calls = {"n": 0}

        def send(query):
            calls["n"] += 1
            if calls["n"] == 1:
                headers = Message()
                headers["Retry-After"] = "0"
                raise urllib.error.HTTPError("http://x", 429, "slow down", headers, None)
            return {"results": {"bindings": []}}

        client = SparqlClient(send=send, sleeper=lambda s: None)
        self.assertEqual(client.query("SELECT"), [])
        self.assertEqual(calls["n"], 2)

    def test_gives_up_eventually(self):
        def send(query):
            headers = Message()
            raise urllib.error.HTTPError("http://x", 500, "boom", headers, None)

        client = SparqlClient(send=send, max_retries=1, sleeper=lambda s: None)
        with self.assertRaises(SparqlError):
            client.query("SELECT")

    def test_unknown_endpoint_rejected(self):
        with self.assertRaises(ValueError):
            SparqlClient(endpoint="nope")


class FakeSparql:
    """Returns prepared pages, repeating the last one when exhausted."""

    def __init__(self, pages):
        self.pages = list(pages)
        self.queries = []

    def query(self, text):
        self.queries.append(text)
        return self.pages.pop(0) if self.pages else []


class TestStage(unittest.TestCase):
    def setUp(self):
        self.conn = sqlite3.connect(":memory:")
        self.conn.row_factory = sqlite3.Row
        ensure_schema(self.conn)
        ensure_wd_schema(self.conn)

    def tearDown(self):
        self.conn.close()

    def test_merges_duplicate_items_and_unions_designations(self):
        client = FakeSparql([list(SAMPLE_ROWS)])
        result = stage(self.conn, client)
        self.assertEqual(result["rows"], 2)
        row = self.conn.execute("SELECT * FROM wd_places WHERE qid='Q1000'").fetchone()
        self.assertEqual(len(json.loads(row["heritage"])), 2)
        self.assertEqual(row["status"], "pending")

    def test_stops_when_page_is_short(self):
        client = FakeSparql([list(SAMPLE_ROWS)])
        stage(self.conn, client, page_size=100)
        self.assertEqual(len(client.queries), 1)

    def test_limit_is_respected(self):
        client = FakeSparql([list(SAMPLE_ROWS), list(SAMPLE_ROWS)])
        result = stage(self.conn, client, page_size=2, limit=2)
        self.assertEqual(result["rows"], 2)

    def test_rerun_does_not_duplicate(self):
        stage(self.conn, FakeSparql([list(SAMPLE_ROWS)]))
        stage(self.conn, FakeSparql([list(SAMPLE_ROWS)]))
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM wd_places").fetchone()[0], 2)


class TestEnrich(unittest.TestCase):
    def setUp(self):
        self.conn = sqlite3.connect(":memory:")
        self.conn.row_factory = sqlite3.Row
        ensure_schema(self.conn)
        ensure_wd_schema(self.conn)
        stage(self.conn, FakeSparql([list(SAMPLE_ROWS)]))

    def _patch_images(self, records):
        import wikicrawl.bulk as bulk

        self._original = bulk.fetch_imageinfo
        bulk.fetch_imageinfo = lambda commons, files: iter(records)

    def tearDown(self):
        if hasattr(self, "_original"):
            import wikicrawl.bulk as bulk

            bulk.fetch_imageinfo = self._original
        self.conn.close()

    def test_creates_places_with_qid_ids_and_photos(self):
        self._patch_images(
            [
                {
                    "file": "File:Grad Snežnik.jpg",
                    "url": "https://upload.wikimedia.org/x.jpg",
                    "width": 1200,
                    "height": 800,
                    "license": "CC BY-SA 4.0",
                    "artist": "Jane",
                    "description_url": "https://commons.wikimedia.org/wiki/File:Grad_Sne%C5%BEnik.jpg",
                }
            ]
        )
        result = enrich(self.conn, commons=None)
        self.assertEqual(result["places"], 2)
        self.assertEqual(result["photos"], 1)
        place = self.conn.execute("SELECT * FROM places WHERE id='wc:Q1000'").fetchone()
        self.assertEqual(place["wikidata_id"], "Q1000")
        self.assertEqual(place["lat"], 45.6012)
        self.assertIsNotNone(place["commons_category"])
        photo = self.conn.execute("SELECT * FROM place_photos WHERE place_id='wc:Q1000'").fetchone()
        self.assertEqual(photo["license"], "CC BY-SA 4.0")

    def test_enrich_is_idempotent(self):
        self._patch_images([])
        enrich(self.conn, commons=None)
        before = self.conn.execute("SELECT COUNT(*) FROM places").fetchone()[0]
        result = enrich(self.conn, commons=None)
        self.assertEqual(result["places"], 0)
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM places").fetchone()[0], before)

    def test_marks_rows_enriched(self):
        self._patch_images([])
        enrich(self.conn, commons=None)
        self.assertEqual(pending(self.conn), [])
        report = status(self.conn)
        self.assertEqual(report["enriched"], 2)
        self.assertEqual(report["pending"], 0)
        self.assertEqual(report["places"], 2)

    def test_heritage_designations_are_stored(self):
        self._patch_images([])
        enrich(self.conn, commons=None)
        row = self.conn.execute(
            "SELECT heritage_designations FROM places WHERE id='wc:Q1000'"
        ).fetchone()
        self.assertEqual(len(json.loads(row["heritage_designations"])), 2)


if __name__ == "__main__":
    unittest.main()
