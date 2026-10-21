"""Tests for the Google Places-shaped clean layer.

The property under test is compatibility: anything we emit must use only field
names that ``places.googleapis.com/v1`` actually defines. The allowed sets below
are copied from Google's discovery document
(``https://places.googleapis.com/$discovery/rest?version=v1``, revision
20261019), so a typo in a serialiser fails here rather than in someone's client.
"""

from __future__ import annotations

import json
import os
import sqlite3
import tempfile
import unittest

from wikicrawl.google import (
    PlacesClient,
    PlacesError,
    best_candidate,
    distance_m,
    match_places,
    name_similarity,
    score_pair,
)
from wikicrawl.normalize import clean_author, normalize, place_id_for, wiki_key
from wikicrawl.schema import (
    ensure_schema,
    infer_types,
    photo_index,
    photo_resource_name,
    place_to_google,
    places_response,
    slugify,
)
from wikicrawl.store import Store

# Places API (New) — GoogleMapsPlacesV1Place
ALLOWED_PLACE_KEYS = {
    "id",
    "displayName",
    "formattedAddress",
    "shortFormattedAddress",
    "adrFormatAddress",
    "location",
    "types",
    "primaryType",
    "websiteUri",
    "googleMapsUri",
    "rating",
    "userRatingCount",
    "businessStatus",
    "photos",
    "addressComponents",
}
# GoogleMapsPlacesV1Photo
ALLOWED_PHOTO_KEYS = {"name", "widthPx", "heightPx", "authorAttributions", "googleMapsUri"}
# GoogleTypeLocalizedText / GoogleTypeLatLng / GoogleMapsPlacesV1AuthorAttribution
ALLOWED_LOCALIZED_KEYS = {"text", "languageCode"}
ALLOWED_LATLNG_KEYS = {"latitude", "longitude"}
ALLOWED_AUTHOR_KEYS = {"displayName", "uri", "photoUri"}

PLACE_ROW = {
    "id": "wc:Q10285",
    "name": "Colosseum",
    "language_code": "en",
    "formatted_address": None,
    "short_formatted_address": None,
    "adr_format_address": None,
    "lat": 41.8902,
    "lng": 12.4922,
    "types": json.dumps(["historical_landmark", "tourist_attraction"]),
    "primary_type": "historical_landmark",
    "business_status": "OPERATIONAL",
    "website_uri": None,
    "google_maps_uri": None,
    "rating": None,
    "user_rating_count": None,
}

PHOTO_ROW = {
    "id": "commons:Colosseo 2020.jpg",
    "place_id": "wc:Q10285",
    "name": "places/wc:Q10285/photos/commons-colosseo-2020",
    "url": "https://upload.wikimedia.org/x.jpg",
    "description_url": "https://commons.wikimedia.org/wiki/File:Colosseo_2020.jpg",
    "width_px": 6000,
    "height_px": 4000,
    "author_name": "Example Photographer",
    "author_uri": "https://commons.wikimedia.org/wiki/User:Example",
    "license": "CC BY-SA 4.0",
}


class TestSerialisation(unittest.TestCase):
    def test_place_payload_uses_only_google_fields(self):
        payload = place_to_google(PLACE_ROW, [PHOTO_ROW])
        self.assertLessEqual(set(payload), ALLOWED_PLACE_KEYS)
        self.assertLessEqual(set(payload["displayName"]), ALLOWED_LOCALIZED_KEYS)
        self.assertLessEqual(set(payload["location"]), ALLOWED_LATLNG_KEYS)
        for photo in payload["photos"]:
            self.assertLessEqual(set(photo), ALLOWED_PHOTO_KEYS)
            for author in photo.get("authorAttributions", []):
                self.assertLessEqual(set(author), ALLOWED_AUTHOR_KEYS)

    def test_envelope_matches_search_response(self):
        body = places_response([place_to_google(PLACE_ROW)])
        self.assertEqual(list(body), ["places"])
        self.assertIsInstance(body["places"], list)

    def test_unset_fields_are_omitted(self):
        payload = place_to_google(PLACE_ROW)
        for absent in ("formattedAddress", "rating", "websiteUri", "googleMapsUri"):
            self.assertNotIn(absent, payload)

    def test_google_fields_pass_through(self):
        row = dict(
            PLACE_ROW,
            formatted_address="Piazza del Colosseo, 1, Roma",
            rating=4.7,
            user_rating_count=123456,
            website_uri="https://example.org",
        )
        payload = place_to_google(row)
        self.assertEqual(payload["formattedAddress"], "Piazza del Colosseo, 1, Roma")
        self.assertEqual(payload["rating"], 4.7)
        self.assertEqual(payload["userRatingCount"], 123456)

    def test_photo_resource_name_shape(self):
        name = photo_resource_name("wc:Q10285", "commons:Colosseo 2020.jpg")
        self.assertEqual(name, "places/wc:Q10285/photos/commons-colosseo-2020")
        self.assertEqual(
            place_to_google(PLACE_ROW, [PHOTO_ROW])["photos"][0]["name"], PHOTO_ROW["name"]
        )

    def test_photo_index_keeps_urls_out_of_payload(self):
        index = photo_index([PHOTO_ROW])
        self.assertIn(PHOTO_ROW["name"], index)
        self.assertEqual(index[PHOTO_ROW["name"]]["url"], PHOTO_ROW["url"])
        self.assertEqual(index[PHOTO_ROW["name"]]["license"], "CC BY-SA 4.0")


class TestTypeInference(unittest.TestCase):
    def test_template_plumbing_does_not_create_zoo(self):
        types = infer_types(
            {
                "title": "Arch of Constantine",
                "categories": ["Category:Ancient Roman triumphal arches in Rome"],
                "infobox": {"mapframe-zoom": "13", "mapframe-marker": "monument"},
            }
        )
        self.assertNotIn("zoo", types)
        self.assertIn("historical_landmark", types)

    def test_maintenance_categories_are_ignored(self):
        types = infer_types(
            {
                "title": "Some Monument",
                "categories": ["Category:Pages using gallery without a media namespace prefix"],
                "infobox": {},
            }
        )
        self.assertNotIn("art_gallery", types)

    def test_hindu_temple_versus_roman_temple(self):
        hindu = infer_types({"title": "X", "categories": ["Category:Hindu temples in India"]})
        roman = infer_types({"title": "Temple of Venus and Roma", "categories": []})
        self.assertEqual(hindu[0], "hindu_temple")
        self.assertNotIn("hindu_temple", roman)

    def test_fallback_is_never_empty(self):
        self.assertEqual(infer_types({"title": "Nowhere"}), ["tourist_attraction"])

    def test_output_stays_in_google_vocabulary(self):
        from wikicrawl.schema import GOOGLE_TYPES

        for vocab in (
            ["Category:Churches in Italy"],
            ["Category:Museums in Rome"],
            ["Category:Castles in Slovenia"],
        ):
            for value in infer_types({"title": "T", "categories": vocab}):
                self.assertIn(value, GOOGLE_TYPES)


class TestSchema(unittest.TestCase):
    def setUp(self):
        self.conn = sqlite3.connect(":memory:")
        self.conn.row_factory = sqlite3.Row
        ensure_schema(self.conn)

    def tearDown(self):
        self.conn.close()

    def test_stale_view_flags_old_google_content(self):
        self.conn.execute(
            "INSERT INTO places (id, name, lat, lng, types, google_place_id, google_fetched_at)"
            " VALUES ('a', 'A', 1, 1, '[]', 'ChIJfresh', strftime('%s','now'))"
        )
        self.conn.execute(
            "INSERT INTO places (id, name, lat, lng, types, google_place_id, google_fetched_at)"
            " VALUES ('b', 'B', 1, 1, '[]', 'ChIJold', strftime('%s','now') - 40*86400)"
        )
        stale = [row["id"] for row in self.conn.execute("SELECT id FROM v_google_stale")]
        self.assertEqual(stale, ["b"])

    def test_place_ids_are_namespaced_and_stable(self):
        self.assertEqual(place_id_for("enwiki", 27119), "wc:enwiki:27119")
        self.assertEqual(place_id_for("enwiki", 27119, "Q10285"), "wc:Q10285")

    def test_slugify(self):
        self.assertEqual(slugify("File:Colosseo (Rome) 2020.JPG"), "colosseo-rome-2020")
        self.assertEqual(slugify(""), "photo")


class TestNormalize(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.store = Store(os.path.join(self.tmp, "crawl.sqlite"))
        self.conn = self.store.conn
        ensure_schema(self.conn)
        self.conn.execute(
            """INSERT INTO pages (pageid, title, url, lat, lon, image, infobox)
               VALUES (1, 'Colosseum', 'https://en.wikipedia.org/wiki/Colosseum',
                       41.8902, 12.4922, 'Colosseo.jpg', '{}')"""
        )
        self.conn.execute(
            "INSERT INTO page_categories (pageid, category)"
            " VALUES (1, 'Category:Ancient Roman amphitheatres')"
        )
        self.conn.execute(
            """INSERT INTO photos (file, url, width, height, license, artist, description_url)
               VALUES ('File:Colosseo.jpg', 'https://upload.wikimedia.org/c.jpg', 6000, 4000,
                       'CC BY-SA 4.0',
                       '<a href="//commons.wikimedia.org/wiki/User:X">Jane Doe</a>',
                       'https://commons.wikimedia.org/wiki/File:Colosseo.jpg')"""
        )
        self.conn.commit()

    def tearDown(self):
        self.store.close()
        for name in os.listdir(self.tmp):
            os.unlink(os.path.join(self.tmp, name))
        os.rmdir(self.tmp)

    def test_builds_places_and_photos(self):
        summary = normalize(self.conn)
        self.assertEqual(summary["places"], 1)
        self.assertEqual(summary["photos"], 1)
        place = self.conn.execute("SELECT * FROM places").fetchone()
        self.assertEqual(place["id"], "wc:enwiki:1")
        self.assertEqual(json.loads(place["types"]), ["historical_landmark"])

        photo = self.conn.execute("SELECT * FROM place_photos").fetchone()
        self.assertEqual(photo["author_name"], "Jane Doe")
        self.assertEqual(photo["author_uri"], "https://commons.wikimedia.org/wiki/User:X")
        self.assertIsNone(photo["google_photo_reference"])

    def test_skips_pages_without_coordinates(self):
        self.conn.execute("UPDATE pages SET lat = NULL")
        summary = normalize(self.conn)
        self.assertEqual(summary["places"], 0)
        self.assertEqual(summary["skipped"], 1)

    def test_is_idempotent(self):
        normalize(self.conn)
        normalize(self.conn)
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM places").fetchone()[0], 1)
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM place_photos").fetchone()[0], 1)

    def test_clean_author_strips_html(self):
        name, uri = clean_author('<a href="https://x/u"> A &amp; B </a>')
        self.assertEqual(name, "A & B")
        self.assertEqual(uri, "https://x/u")

    def test_wiki_key(self):
        self.assertEqual(wiki_key("https://de.wikipedia.org/wiki/X"), "dewiki")
        self.assertEqual(wiki_key(""), "enwiki")


class TestPlacesClient(unittest.TestCase):
    def setUp(self):
        self.sent = []

        def send(url, body, headers, timeout=30):
            self.sent.append({"url": url, "body": body, "headers": headers})
            return {"places": []}

        self.client = PlacesClient("test-key", send=send)

    def test_search_nearby_request_shape(self):
        self.client.search_nearby(41.89, 12.49, radius_m=400, included_types=["museum"])
        sent = self.sent[0]
        self.assertTrue(sent["url"].endswith("places:searchNearby"))
        self.assertEqual(sent["body"]["locationRestriction"]["circle"]["radius"], 400.0)
        self.assertEqual(sent["body"]["includedTypes"], ["museum"])
        self.assertEqual(sent["headers"]["X-Goog-Api-Key"], "test-key")
        self.assertIn("places.photos.name", sent["headers"]["X-Goog-FieldMask"])

    def test_nearby_clamps_result_count(self):
        self.client.search_nearby(0, 0, max_results=99)
        self.assertEqual(self.sent[0]["body"]["maxResultCount"], 20)

    def test_radius_out_of_range_is_rejected(self):
        with self.assertRaises(ValueError):
            self.client.search_nearby(0, 0, radius_m=60000)

    def test_search_text_biases_to_point(self):
        self.client.search_text("Colosseum", lat=41.89, lon=12.49, radius_m=250)
        body = self.sent[0]["body"]
        self.assertEqual(body["textQuery"], "Colosseum")
        self.assertEqual(body["locationBias"]["circle"]["radius"], 250.0)

    def test_transport_error_becomes_places_error(self):
        import urllib.error
        from email.message import Message

        def broken(url, body, headers, timeout=30):
            raise urllib.error.HTTPError(url, 403, "forbidden", Message(), None)

        with self.assertRaises(PlacesError):
            PlacesClient("k", send=broken).search_text("x")


class TestMatching(unittest.TestCase):
    def test_name_similarity(self):
        self.assertGreater(name_similarity("Colosseum", "Colosseum"), 0.95)
        self.assertGreater(name_similarity("Colosseum", "The Colosseum"), 0.8)
        self.assertLess(name_similarity("Colosseum", "Colosseo Metro"), 0.6)
        self.assertEqual(name_similarity("", "X"), 0.0)

    def test_distance(self):
        self.assertLess(distance_m(41.8902, 12.4922, 41.8902, 12.4922), 1)
        self.assertAlmostEqual(distance_m(0, 0, 0, 1), 111195, delta=200)

    def test_score_rejects_far_candidates(self):
        candidate = {
            "displayName": {"text": "Colosseum"},
            "location": {"latitude": 45.0, "longitude": 9.0},
        }
        self.assertEqual(score_pair("Colosseum", 41.89, 12.49, candidate), 0.0)

    def test_best_candidate_prefers_closest_name_match(self):
        response = {
            "places": [
                {
                    "id": "A",
                    "displayName": {"text": "Colosseo Metro"},
                    "location": {"latitude": 41.8905, "longitude": 12.4923},
                },
                {
                    "id": "B",
                    "displayName": {"text": "Colosseum"},
                    "location": {"latitude": 41.8903, "longitude": 12.4923},
                },
            ]
        }
        candidate, score = best_candidate("Colosseum", 41.8902, 12.4922, response)
        self.assertEqual(candidate["id"], "B")
        self.assertGreater(score, 0.7)


class TestMatchPlaces(unittest.TestCase):
    def setUp(self):
        self.conn = sqlite3.connect(":memory:")
        self.conn.row_factory = sqlite3.Row
        ensure_schema(self.conn)
        self.conn.execute(
            "INSERT INTO places (id, name, lat, lng, types) VALUES ('wc:Q10285', 'Colosseum', 41.8902, 12.4922, '[]')"
        )
        self.conn.commit()

    def tearDown(self):
        self.conn.close()

    def _client(self, payload):
        calls = []

        def send(url, body, headers, timeout=30):
            calls.append(body)
            return payload

        client = PlacesClient("k", send=send)
        client.calls = calls
        return client

    def test_accepts_a_confident_match(self):
        client = self._client(
            {
                "places": [
                    {
                        "id": "ChIJrTLr-GyuEmsRBfy61i59si0",
                        "displayName": {"text": "Colosseum"},
                        "location": {"latitude": 41.8903, "longitude": 12.4923},
                    }
                ]
            }
        )
        summary = match_places(self.conn, client)
        self.assertEqual(summary["matched"], 1)
        row = self.conn.execute("SELECT google_place_id, match_confidence FROM places").fetchone()
        self.assertEqual(row["google_place_id"], "ChIJrTLr-GyuEmsRBfy61i59si0")
        self.assertGreater(row["match_confidence"], 0.7)

    def test_rejects_a_weak_candidate(self):
        client = self._client(
            {
                "places": [
                    {
                        "id": "ChIJwrong",
                        "displayName": {"text": "Pizzeria da Mario"},
                        "location": {"latitude": 41.8903, "longitude": 12.4923},
                    }
                ]
            }
        )
        summary = match_places(self.conn, client, threshold=0.55)
        self.assertEqual(summary["rejected"], 1)
        row = self.conn.execute("SELECT google_place_id FROM places").fetchone()
        self.assertIsNone(row["google_place_id"])

    def test_does_not_store_google_fields_by_default(self):
        client = self._client(
            {
                "places": [
                    {
                        "id": "ChIJx",
                        "displayName": {"text": "Colosseum"},
                        "formattedAddress": "Piazza del Colosseo, Roma",
                        "location": {"latitude": 41.8903, "longitude": 12.4923},
                    }
                ]
            }
        )
        match_places(self.conn, client)
        row = self.conn.execute("SELECT formatted_address FROM places").fetchone()
        self.assertIsNone(row["formatted_address"])

    def test_store_fields_writes_address_and_stamp(self):
        client = self._client(
            {
                "places": [
                    {
                        "id": "ChIJx",
                        "displayName": {"text": "Colosseum"},
                        "formattedAddress": "Piazza del Colosseo, Roma",
                        "location": {"latitude": 41.8903, "longitude": 12.4923},
                    }
                ]
            }
        )
        match_places(self.conn, client, store_fields=True)
        row = self.conn.execute(
            "SELECT formatted_address, google_fetched_at FROM places"
        ).fetchone()
        self.assertEqual(row["formatted_address"], "Piazza del Colosseo, Roma")
        self.assertIsNotNone(row["google_fetched_at"])

    def test_dry_run_writes_nothing(self):
        client = self._client({"places": []})
        summary = match_places(self.conn, client, dry_run=True, log=lambda *_: None)
        self.assertEqual(summary["requests"], 1)
        self.assertEqual(client.calls, [])
        self.assertIsNone(self.conn.execute("SELECT google_place_id FROM places").fetchone()[0])


if __name__ == "__main__":
    unittest.main()
