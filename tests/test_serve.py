"""Tests for the slim serving database and the Places-compatible server."""

from __future__ import annotations

import json
import os
import sqlite3
import tempfile
import threading
import unittest
import urllib.error
import urllib.request

from placeswiki.schema import ensure_schema
from placeswiki.serve import (
    BadRequest,
    PlaceIndex,
    apply_mask,
    make_server,
    parse_field_mask,
)
from placeswiki.slim import build_slim


def make_source(path):
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    ensure_schema(conn)
    places = [
        ("wc:Q1", "Near Place", 46.0503, 14.5045, '["historical_landmark"]'),
        ("wc:Q2", "Far Place", 46.2000, 14.7000, '["church"]'),
        ("wc:Q3", "Another Near", 46.0505, 14.5047, '["museum"]'),
    ]
    for place_id, name, lat, lng, types in places:
        conn.execute(
            "INSERT INTO places (id, name, lat, lng, types, primary_type) VALUES (?, ?, ?, ?, ?, ?)",
            (place_id, name, lat, lng, types, json.loads(types)[0]),
        )
    conn.execute(
        "INSERT INTO place_photos (id, place_id, name, url, width_px, height_px, license, author_name)"
        " VALUES ('commons:a.jpg', 'wc:Q1', 'places/wc:Q1/photos/a', 'https://u/a', 10, 20,"
        " 'CC BY-SA 4.0', 'Jane')"
    )
    # provenance table that slim must drop
    conn.execute("CREATE TABLE pages (pageid INTEGER PRIMARY KEY, title TEXT)")
    conn.execute("INSERT INTO pages (pageid, title) VALUES (1, 'Near Place')")
    conn.commit()
    conn.close()


class TestFieldMask(unittest.TestCase):
    def test_empty_mask_means_everything(self):
        self.assertIsNone(parse_field_mask(""))
        self.assertIsNone(parse_field_mask(None))

    def test_top_level_fields(self):
        mask = parse_field_mask("places.id,places.displayName")
        self.assertEqual(mask, {"id": set(), "displayName": set()})

    def test_nested_fields(self):
        mask = parse_field_mask("places.photos.name")
        self.assertEqual(mask, {"photos": {"name": set()}})

    def test_star_means_everything(self):
        self.assertIsNone(parse_field_mask("places.*"))

    def test_apply_mask_projects(self):
        place = {
            "id": "x",
            "displayName": {"text": "T", "languageCode": "en"},
            "photos": [{"name": "p", "widthPx": 10}],
        }
        masked = apply_mask(place, {"displayName": {"text": set()}, "photos": {"name": set()}})
        self.assertEqual(masked, {"displayName": {"text": "T"}, "photos": [{"name": "p"}]})


class TestSlim(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.source = os.path.join(self.tmp, "source.sqlite")
        self.slim = os.path.join(self.tmp, "slim.sqlite")
        make_source(self.source)

    def tearDown(self):
        for name in os.listdir(self.tmp):
            os.unlink(os.path.join(self.tmp, name))
        os.rmdir(self.tmp)

    def test_build_only_copies_serving_tables(self):
        stats = build_slim(self.source, self.slim)
        self.assertEqual(stats["places"], 3)
        self.assertEqual(stats["photos"], 1)
        conn = sqlite3.connect(self.slim)
        tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        conn.close()
        self.assertEqual(tables, {"places", "place_photos"})
        self.assertLessEqual(stats["slim_bytes"], stats["source_bytes"])

    def test_existing_file_requires_force(self):
        build_slim(self.source, self.slim)
        with self.assertRaises(FileExistsError):
            build_slim(self.source, self.slim)
        build_slim(self.source, self.slim, overwrite=True)


class TestIndex(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.db = os.path.join(self.tmp, "slim.sqlite")
        source = os.path.join(self.tmp, "source.sqlite")
        make_source(source)
        build_slim(source, self.db)
        os.unlink(source)
        self.index = PlaceIndex(self.db)

    def tearDown(self):
        self.index.close()
        for name in os.listdir(self.tmp):
            os.unlink(os.path.join(self.tmp, name))
        os.rmdir(self.tmp)

    def test_nearby_is_ordered_and_radius_bounded(self):
        places = self.index.nearby(46.0503, 14.5045, 200)
        self.assertEqual([p["id"] for p in places], ["wc:Q1", "wc:Q3"])
        wide = self.index.nearby(46.0503, 14.5045, 50000)
        self.assertEqual(len(wide), 3)

    def test_nearby_type_filter(self):
        places = self.index.nearby(46.0503, 14.5045, 50000, included_types=["museum"])
        self.assertEqual([p["id"] for p in places], ["wc:Q3"])

    def test_nearby_caps_at_twenty(self):
        with self.assertRaises(BadRequest):
            self.index.nearby(1, 1, 0)

    def test_nearby_rejects_bad_radius(self):
        with self.assertRaises(BadRequest):
            self.index.nearby(46.0, 14.5, 0)

    def test_text_search_ranks_by_distance_when_biased(self):
        places = self.index.text_search("Place", lat=46.2, lon=14.7)
        self.assertEqual(places[0]["id"], "wc:Q2")

    def test_get_by_our_id(self):
        self.assertEqual(self.index.get("wc:Q1")["displayName"]["text"], "Near Place")

    def test_get_unknown_raises(self):
        from placeswiki.serve import NotFound

        with self.assertRaises(NotFound):
            self.index.get("wc:nope")


class TestHTTP(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp()
        source = os.path.join(cls.tmp, "source.sqlite")
        slim = os.path.join(cls.tmp, "slim.sqlite")
        make_source(source)
        build_slim(source, slim)
        os.unlink(source)
        cls.server = make_server(slim, port=0)
        cls.port = cls.server.server_address[1]
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.server.index.close()
        for name in os.listdir(cls.tmp):
            os.unlink(os.path.join(cls.tmp, name))
        os.rmdir(cls.tmp)

    def _post(self, path, payload, mask=None):
        req = urllib.request.Request(
            "http://127.0.0.1:%d%s" % (self.port, path),
            data=json.dumps(payload).encode(),
            headers={
                "Content-Type": "application/json",
                **({"X-Goog-FieldMask": mask} if mask else {}),
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=10) as response:
                return response.status, json.loads(response.read())
        except urllib.error.HTTPError as exc:
            return exc.code, json.loads(exc.read())

    def test_nearby_returns_google_envelope(self):
        status, body = self._post(
            "/v1/places:searchNearby",
            {
                "locationRestriction": {
                    "circle": {"center": {"latitude": 46.05, "longitude": 14.5}, "radius": 5000}
                },
                "maxResultCount": 2,
            },
        )
        self.assertEqual(status, 200)
        self.assertIn("places", body)
        self.assertEqual(len(body["places"]), 2)
        self.assertIn("displayName", body["places"][0])

    def test_field_mask_limits_fields(self):
        _, body = self._post(
            "/v1/places:searchNearby",
            {
                "locationRestriction": {
                    "circle": {"center": {"latitude": 46.05, "longitude": 14.5}, "radius": 5000}
                },
            },
            mask="places.id,places.displayName",
        )
        self.assertEqual(set(body["places"][0]), {"id", "displayName"})

    def test_bad_body_is_400(self):
        status, body = self._post("/v1/places:searchNearby", {"locationRestriction": {}})
        self.assertEqual(status, 400)
        self.assertEqual(body["error"]["status"], "INVALID_ARGUMENT")

    def test_unknown_path_is_404(self):
        status, body = self._post("/v2/nope", {})
        self.assertEqual(status, 404)
        self.assertEqual(body["error"]["status"], "NOT_FOUND")

    def test_health_and_meta(self):
        for path in ("/health", "/v1/meta"):
            with urllib.request.urlopen(
                "http://127.0.0.1:%d%s" % (self.port, path), timeout=10
            ) as r:
                self.assertEqual(r.status, 200)
                json.loads(r.read())


if __name__ == "__main__":
    unittest.main()
