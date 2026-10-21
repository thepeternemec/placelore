"""Tests for the redistributable bundle."""

from __future__ import annotations

import json
import os
import sqlite3
import tempfile
import unittest

from wikicrawl.publish import attribution_markdown, publish, sha256
from wikicrawl.schema import ensure_schema


class TestPublish(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.db = os.path.join(self.tmp, "src.sqlite")
        self.out = os.path.join(self.tmp, "bundle")
        conn = sqlite3.connect(self.db)
        conn.row_factory = sqlite3.Row
        ensure_schema(conn)
        conn.execute(
            "INSERT INTO places (id, name, lat, lng, types, primary_type)"
            " VALUES ('wc:Q1', 'Test Monument', 46.0, 14.5, '[\"historical_landmark\"]',"
            " 'historical_landmark')"
        )
        conn.execute(
            "INSERT INTO place_photos (id, place_id, name, url, license, author_name, author_uri)"
            " VALUES ('commons:Test.jpg', 'wc:Q1',"
            " 'places/wc:Q1/photos/commons-test', 'https://upload.wikimedia.org/t.jpg',"
            " 'CC BY-SA 4.0', 'Jane Doe', 'https://commons.wikimedia.org/wiki/User:Jane')"
        )
        conn.execute(
            "INSERT INTO place_links (place_id, google_place_id, is_primary, method, confidence)"
            " VALUES ('wc:Q1', 'ChIJabcdefghijklmnopqrstuvwx', 1, 'import', 0.9)"
        )
        conn.commit()
        conn.close()

    def tearDown(self):
        for root, _dirs, files in os.walk(self.tmp, topdown=False):
            for name in files:
                os.unlink(os.path.join(root, name))
            for name in _dirs:
                os.rmdir(os.path.join(root, name))
        os.rmdir(self.tmp)

    def test_bundle_contents_and_hashes(self):
        manifest = publish(self.db, self.out, name="test-bundle")
        for filename in (
            "places.jsonl",
            "places.json",
            "photos.json",
            "links.json",
            "ATTRIBUTION.md",
            "datapackage.json",
            "README.md",
        ):
            self.assertTrue(os.path.exists(os.path.join(self.out, filename)), filename)

        for resource in manifest["resources"]:
            path = os.path.join(self.out, resource["path"])
            self.assertEqual(resource["hash"], "sha256:" + sha256(path))
            self.assertEqual(resource["bytes"], os.path.getsize(path))

        self.assertEqual(manifest["counts"]["places"], 1)
        self.assertEqual(manifest["counts"]["photos"], 1)
        self.assertEqual(manifest["counts"]["links"], 1)

    def test_places_jsonl_is_google_shaped(self):
        publish(self.db, self.out)
        with open(os.path.join(self.out, "places.jsonl"), encoding="utf-8") as handle:
            place = json.loads(handle.readline())
        self.assertEqual(place["id"], "wc:Q1")
        self.assertIn("location", place)
        self.assertIn("photos", place)

    def test_attribution_names_every_photo_resource(self):
        publish(self.db, self.out)
        with open(os.path.join(self.out, "photos.json"), encoding="utf-8") as handle:
            photos = json.load(handle)
        with open(os.path.join(self.out, "ATTRIBUTION.md"), encoding="utf-8") as handle:
            attribution = handle.read()
        for name in photos:
            self.assertIn(name, attribution)
        self.assertIn("Jane Doe", attribution)
        self.assertIn("CC BY-SA 4.0", attribution)

    def test_datapackage_declares_licences_and_sources(self):
        publish(self.db, self.out)
        with open(os.path.join(self.out, "datapackage.json"), encoding="utf-8") as handle:
            manifest = json.load(handle)
        self.assertTrue(manifest["licenses"])
        titles = [source["title"] for source in manifest["sources"]]
        self.assertTrue(any("Wikimedia" in title for title in titles))
        self.assertEqual(manifest["attribution"], "ATTRIBUTION.md")
        self.assertIn("time-limited", manifest["notes"])

    def test_rerun_is_deterministic_for_hashes(self):
        first = publish(self.db, self.out)
        second = publish(self.db, self.out)
        hashes_first = {r["path"]: r["hash"] for r in first["resources"]}
        hashes_second = {r["path"]: r["hash"] for r in second["resources"]}
        self.assertEqual(hashes_first, hashes_second)


class TestAttribution(unittest.TestCase):
    def test_unknown_author_and_licence_are_labelled(self):
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        ensure_schema(conn)
        conn.execute("INSERT INTO places (id, name, lat, lng, types) VALUES ('p', 'P', 1, 1, '[]')")
        conn.execute(
            "INSERT INTO place_photos (id, place_id, name, url) VALUES"
            " ('commons:x', 'p', 'places/p/photos/x', 'https://u/x')"
        )
        text = attribution_markdown(conn)
        self.assertIn("unknown author", text)
        self.assertIn("unknown", text)
        conn.close()


if __name__ == "__main__":
    unittest.main()
