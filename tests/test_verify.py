"""Tests for the Google-compatibility check.

These skip when ``google-maps-places`` is absent, so the crawler stays
standard-library only. CI installs it and runs the same tests, which is what
turns "the payload is Google-shaped" into a checked claim.
"""

from __future__ import annotations

import json
import os
import unittest

from wikicrawl.verify import format_report, verify_payload

FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures")

try:  # optional dependency
    import google.maps.places_v1  # noqa: F401
    import google.protobuf  # noqa: F401

    HAVE_GOOGLE = True
except ImportError:  # pragma: no cover - environment dependent
    HAVE_GOOGLE = False


def load(name):
    with open(os.path.join(FIXTURES, name), encoding="utf-8") as handle:
        return json.load(handle)


class TestReportFormatting(unittest.TestCase):
    def test_ok_report(self):
        text = format_report({"places": 2, "parsed": 2, "problems": []})
        self.assertIn("parsed 2/2 places", text)
        self.assertTrue(text.endswith("OK"))

    def test_failure_report_lists_problems(self):
        text = format_report(
            {"places": 2, "parsed": 1, "problems": [("wc:enwiki:1", "ParseError: bad")]}
        )
        self.assertIn("FAILED", text)
        self.assertIn("wc:enwiki:1", text)


@unittest.skipUnless(HAVE_GOOGLE, "google-maps-places not installed")
class TestGoogleParsing(unittest.TestCase):
    def test_fixture_parses(self):
        payload = load("google-payload.json")
        index = load("google-photo-index.json")
        result = verify_payload(payload, index)
        self.assertEqual(result["problems"], [])
        self.assertEqual(result["parsed"], result["places"])

    def test_wrong_scalar_type_is_caught(self):
        payload = load("google-payload.json")
        payload["places"][0]["location"]["latitude"] = "not-a-number"
        result = verify_payload(payload)
        self.assertEqual(result["parsed"], len(payload["places"]) - 1)
        self.assertTrue(result["problems"])

    def test_unknown_field_is_rejected(self):
        payload = load("google-payload.json")
        payload["places"][0]["notAGoogleField"] = True
        result = verify_payload(payload)
        self.assertTrue(result["problems"])

    def test_missing_photo_index_entry_is_caught(self):
        payload = load("google-payload.json")
        result = verify_payload(payload, photo_index={})
        self.assertTrue(any("missing from index" in detail for _, detail in result["problems"]))

    def test_bad_envelope_is_reported(self):
        result = verify_payload({"items": []})
        self.assertTrue(result["problems"])
        self.assertEqual(result["places"], 0)

    def test_empty_payload_is_valid(self):
        result = verify_payload({"places": []})
        self.assertEqual(result["problems"], [])


class TestFixtureShape(unittest.TestCase):
    """The committed fixture must keep exercising the fields that matter."""

    def test_fixture_covers_photo_and_types(self):
        payload = load("google-payload.json")
        place = payload["places"][0]
        self.assertIn("photos", place)
        self.assertIn("types", place)
        self.assertIn("location", place)
        self.assertIn("displayName", place)

    def test_index_covers_every_photo(self):
        payload = load("google-payload.json")
        index = load("google-photo-index.json")
        names = {p["name"] for place in payload["places"] for p in place.get("photos", [])}
        self.assertLessEqual(names, set(index))


if __name__ == "__main__":
    unittest.main()
