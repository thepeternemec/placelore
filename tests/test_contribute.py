"""Tests for the upstream-gap report."""

from __future__ import annotations

import json
import sqlite3
import unittest

from placelore.contribute import collect_gaps, render_json, render_markdown
from placelore.schema import ensure_schema


class Base(unittest.TestCase):
    def setUp(self):
        self.conn = sqlite3.connect(":memory:")
        self.conn.row_factory = sqlite3.Row
        ensure_schema(self.conn)
        # complete place: photo, category, article, designation, coords
        self.conn.execute(
            """INSERT INTO places (id, name, lat, lng, types, commons_category,
                                  wikipedia_url, heritage_designations)
               VALUES ('wc:Q1', 'Complete', 46.0, 14.0, '[]', 'Cat', 'https://en.wikipedia.org/wiki/X',
                       '["Q2"]')"""
        )
        self.conn.execute(
            """INSERT INTO place_photos (id, place_id, name, url, license, author_name)
               VALUES ('commons:a.jpg', 'wc:Q1', 'places/wc:Q1/photos/a', 'https://u/a',
                       'CC BY-SA 4.0', 'Jane')"""
        )
        # bare place: nothing but coordinates
        self.conn.execute(
            "INSERT INTO places (id, name, lat, lng, types) VALUES ('wc:Q2', 'Bare', 45.0, 13.0, '[]')"
        )
        # photo with no attribution
        self.conn.execute(
            """INSERT INTO place_photos (id, place_id, name, url)
               VALUES ('commons:b.jpg', 'wc:Q2', 'places/wc:Q2/photos/b', 'https://u/b')"""
        )
        # place with no photo at all
        self.conn.execute(
            "INSERT INTO places (id, name, lat, lng, types) VALUES ('wc:Q3', 'Unphotographed', 44.0, 12.0, '[]')"
        )
        self.conn.commit()

    def tearDown(self):
        self.conn.close()


class TestCollect(Base):
    def test_counts_are_complete_and_items_capped(self):
        gaps = collect_gaps(self.conn, limit=1)
        self.assertEqual(gaps["no_photo"]["count"], 1)
        self.assertEqual(len(gaps["no_photo"]["items"]), 1)
        self.assertEqual(gaps["no_category"]["count"], 2)
        self.assertEqual(gaps["no_article"]["count"], 2)
        self.assertEqual(gaps["no_designation"]["count"], 2)

    def test_complete_place_is_not_reported(self):
        gaps = collect_gaps(self.conn)
        reported = {item["place_id"] for section in gaps.values() for item in section["items"]}
        self.assertNotIn("wc:Q1", reported)

    def test_photo_gaps(self):
        gaps = collect_gaps(self.conn)
        self.assertEqual(gaps["photo_no_author"]["count"], 1)
        self.assertEqual(gaps["photo_no_licence"]["count"], 1)

    def test_items_link_to_wikidata(self):
        gaps = collect_gaps(self.conn)
        item = gaps["no_photo"]["items"][0]
        self.assertEqual(item["wikidata"], "https://www.wikidata.org/wiki/Q3")


class TestRender(Base):
    def test_markdown_has_sections_and_links(self):
        text = render_markdown(collect_gaps(self.conn), source="test.sqlite")
        self.assertIn("Missing a photograph", text)
        self.assertIn("https://www.wikidata.org/wiki/Q2", text)
        self.assertIn("This project writes nothing to Wikimedia", text)

    def test_markdown_notes_truncation(self):
        text = render_markdown(collect_gaps(self.conn, limit=1))
        self.assertIn("more_", text.replace("...", "").replace("…", ""))

    def test_json_is_machine_readable(self):
        payload = json.loads(render_json(collect_gaps(self.conn)))
        self.assertIn("no_photo", payload)
        self.assertEqual(payload["no_photo"]["count"], 1)


if __name__ == "__main__":
    unittest.main()
