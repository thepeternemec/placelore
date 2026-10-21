"""Offline tests: no network, no credentials, deterministic."""

from __future__ import annotations

import json
import os
import tempfile
import unittest
import urllib.error
from email.message import Message

from wikicrawl.api import APIError, MediaWiki
from wikicrawl.crawl import GeoResult, crawl_category, crawl_links, geosearch, grid_centers
from wikicrawl.extract import parse_coordinate_template, parse_infobox, strip_markup, summary
from wikicrawl.images import fetch_imageinfo
from wikicrawl.pages import fetch_pages
from wikicrawl.store import Store


class ScriptedAPI(MediaWiki):
    """A MediaWiki client whose transport is a scripted list of responses."""

    def __init__(self, responses):
        super().__init__("http://test.invalid/w/api.php", min_interval=0, sleeper=self._no_sleep)
        self.responses = list(responses)
        self.urls = []
        self.sleeps = []

    def _no_sleep(self, seconds):
        self.sleeps.append(seconds)

    def _fetch(self, url):
        self.urls.append(url)
        item = self.responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


def http_error(code, retry_after=None):
    headers = Message()
    if retry_after is not None:
        headers["Retry-After"] = str(retry_after)
    return urllib.error.HTTPError("http://test.invalid", code, "error", headers, None)


class TestAPIClient(unittest.TestCase):
    def test_retries_after_429_and_honours_retry_after(self):
        api = ScriptedAPI([http_error(429, retry_after=0), {"query": {"ok": 1}}])
        payload = api.get({"action": "query"})
        self.assertEqual(payload["query"]["ok"], 1)
        self.assertEqual(len(api.urls), 2)
        self.assertIn(0.0, api.sleeps)

    def test_retries_on_maxlag_error(self):
        api = ScriptedAPI(
            [
                {"error": {"code": "maxlag", "info": "Waiting for db", "lag": 0}},
                {"query": {"ok": 2}},
            ]
        )
        self.assertEqual(api.get({"action": "query"})["query"]["ok"], 2)

    def test_raises_on_other_api_errors(self):
        api = ScriptedAPI([{"error": {"code": "badtoken", "info": "nope"}}])
        with self.assertRaises(APIError):
            api.get({"action": "query"})

    def test_paginate_follows_continue_tokens(self):
        api = ScriptedAPI(
            [
                {"query": {"categorymembers": [{"title": "A"}]}, "continue": {"cmcontinue": "x"}},
                {"query": {"categorymembers": [{"title": "B"}]}},
            ]
        )
        titles = [m["title"] for m in api.paginate(list="categorymembers", cmtitle="C")]
        self.assertEqual(titles, ["A", "B"])
        self.assertIn("cmcontinue=x", api.urls[1])

    def test_query_adds_defaults(self):
        api = ScriptedAPI([{"query": {}}])
        api.query(titles="A")
        self.assertIn("formatversion=2", api.urls[0])
        self.assertIn("maxlag=5", api.urls[0])


class TestExtract(unittest.TestCase):
    def test_strip_markup_removes_refs_templates_links(self):
        raw = "The '''Colosseum'''<ref>{{cite book}}</ref> is in [[Rome|Roma]]."
        self.assertEqual(strip_markup(raw), "The Colosseum is in Roma.")

    def test_parse_infobox_handles_nested_templates(self):
        wikitext = (
            "{{Infobox monument\n"
            "| name = Colosseum\n"
            "| height = {{convert|48|m|ft}}\n"
            "| image = [[File:Colosseo.jpg|thumb|The Colosseum]]\n"
            "| built = 80 AD\n"
            "}}\n"
        )
        fields = parse_infobox(wikitext)
        self.assertEqual(fields["name"], "Colosseum")
        self.assertEqual(fields["built"], "80 AD")
        self.assertNotIn("thumb", fields.get("image", ""))
        self.assertEqual(fields["height"], "48 m")

    def test_parse_infobox_returns_empty_without_infobox(self):
        self.assertEqual(parse_infobox("Just prose."), {})

    def test_parse_coordinate_template(self):
        north = parse_coordinate_template("{{coord|46|3|N|14|30|E}}")
        self.assertAlmostEqual(north["lat"], 46.05, places=4)
        self.assertAlmostEqual(north["lon"], 14.5, places=4)
        south = parse_coordinate_template("{{coord|41|53|S|12|29|W}}")
        self.assertAlmostEqual(south["lat"], -41.8833, places=3)
        self.assertAlmostEqual(south["lon"], -12.4833, places=3)
        self.assertIsNone(parse_coordinate_template("no coords here"))

    def test_summary_skips_infobox_and_file_lines(self):
        wikitext = (
            "{{Infobox building\n| name = X\n}}\n\n"
            "[[Category:Buildings]]\n\n"
            "'''X''' is a historic building in the old town, built in 1520.\n"
        )
        text = summary(wikitext)
        self.assertTrue(text.startswith("X is a historic building"))
        self.assertNotIn("Infobox", text)


class FakeCatalogAPI:
    """Minimal API for crawl strategies."""

    def __init__(self, categories=None, links=None, geo=None):
        self.categories = categories or {}
        self.links = links or {}
        self.geo = geo or []
        self.geo_calls = []

    def paginate(self, **params):
        if "cmtitle" in params:
            for title, ns in self.categories.get(params["cmtitle"], []):
                yield {"ns": ns, "title": title}
        elif "titles" in params:
            for title in self.links.get(params["titles"], []):
                yield {"title": title}

    def get(self, **params):
        self.geo_calls.append(dict(params))
        return {"query": {"geosearch": list(self.geo)}}


class TestCrawlStrategies(unittest.TestCase):
    def test_crawl_category_respects_depth_and_filters_namespace(self):
        api = FakeCatalogAPI(
            categories={
                "Category:Root": [("Category:Sub", 14), ("Article A", 0), ("File:X.jpg", 6)],
                "Category:Sub": [("Article B", 0), ("Category:Deep", 14)],
                "Category:Deep": [("Article C", 0)],
            }
        )
        self.assertEqual(sorted(crawl_category(api, ["Root"], depth=0)), ["Article A"])
        self.assertEqual(sorted(crawl_category(api, ["Root"], depth=1)), ["Article A", "Article B"])
        self.assertEqual(
            sorted(crawl_category(api, ["Root"], depth=5)), ["Article A", "Article B", "Article C"]
        )

    def test_crawl_category_survives_cycles(self):
        api = FakeCatalogAPI(
            categories={
                "Category:A": [("Category:B", 14)],
                "Category:B": [("Category:A", 14), ("Article", 0)],
            }
        )
        self.assertEqual(list(crawl_category(api, ["A"], depth=9)), ["Article"])

    def test_crawl_links_stops_at_depth(self):
        api = FakeCatalogAPI(links={"Seed": ["A", "B"], "A": ["C"], "B": [], "C": []})
        self.assertEqual(sorted(crawl_links(api, ["Seed"], depth=1)), ["A", "B", "Seed"])
        self.assertEqual(sorted(crawl_links(api, ["Seed"], depth=2)), ["A", "B", "C", "Seed"])

    def test_grid_centers_stay_inside_radius(self):
        centers = grid_centers(46.05, 14.50, radius=300, cell=100)
        self.assertGreater(len(centers), 5)
        for lat, lon in centers:
            dy = (lat - 46.05) * 111320.0
            dx = (lon - 14.50) * 111320.0 * 0.694  # cos(46.05)
            self.assertLessEqual((dy * dy + dx * dx) ** 0.5, 320)

    def test_geosearch_dedupes_and_flags_capping(self):
        hits = [{"pageid": 1, "title": "A", "dist": 10}, {"pageid": 2, "title": "B", "dist": 20}]
        api = FakeCatalogAPI(geo=hits)
        result = geosearch(api, 46.05, 14.50, radius=100, cell=100)
        self.assertIsInstance(result, GeoResult)
        self.assertEqual(len(result), 2)
        self.assertEqual(len(api.geo_calls), len(grid_centers(46.05, 14.50, 100, 100)))
        self.assertTrue(result.complete)

    def test_geosearch_rejects_out_of_range_radius(self):
        with self.assertRaises(ValueError):
            geosearch(FakeCatalogAPI(), 0, 0, radius=20000)


class TestPages(unittest.TestCase):
    def test_fetch_pages_batches_and_parses(self):
        payload = {
            "query": {
                "pages": [
                    {
                        "pageid": 1,
                        "title": "Colosseum",
                        "coordinates": [{"lat": 41.89, "lon": 12.49, "primary": True}],
                        "pageimage": "Colosseo.jpg",
                        "original": {"source": "https://upload.wikimedia.org/x.jpg"},
                        "extract": "An amphitheatre.",
                        "categories": [{"title": "Category:Colosseum"}],
                        "revisions": [
                            {"slots": {"main": {"content": "{{Infobox monument|built=80 AD}}"}}}
                        ],
                    },
                    {"title": "Missing page", "missing": True},
                ]
            }
        }
        api = ScriptedAPI([payload])
        records = fetch_pages(api, ["Colosseum", "Missing page"])
        self.assertEqual(len(records), 1)
        record = records[0]
        self.assertEqual(record["lat"], 41.89)
        self.assertEqual(record["image"], "Colosseo.jpg")
        self.assertEqual(record["infobox"]["built"], "80 AD")
        self.assertEqual(record["categories"], ["Category:Colosseum"])

    def test_fetch_pages_splits_into_twenty(self):
        api = ScriptedAPI([{"query": {"pages": []}} for _ in range(2)])
        fetch_pages(api, ["T%d" % i for i in range(25)])
        self.assertEqual(len(api.urls), 2)


class TestImages(unittest.TestCase):
    def test_fetch_imageinfo_maps_metadata(self):
        payload = {
            "query": {
                "pages": [
                    {
                        "title": "File:Colosseo.jpg",
                        "imageinfo": [
                            {
                                "url": "https://upload.wikimedia.org/a.jpg?utm_source=x",
                                "width": 1200,
                                "height": 800,
                                "mime": "image/jpeg",
                                "descriptionurl": "https://commons.wikimedia.org/wiki/File:Colosseo.jpg",
                                "extmetadata": {
                                    "LicenseShortName": {"value": "CC BY-SA 4.0"},
                                    "Artist": {"value": "<a>Someone</a>"},
                                },
                            }
                        ],
                    }
                ]
            }
        }
        api = ScriptedAPI([payload])
        records = list(fetch_imageinfo(api, ["Colosseo.jpg"]))
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["url"], "https://upload.wikimedia.org/a.jpg")
        self.assertEqual(records[0]["license"], "CC BY-SA 4.0")
        self.assertEqual(records[0]["width"], 1200)


class TestStore(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.db = os.path.join(self.tmp, "test.sqlite")

    def tearDown(self):
        for name in os.listdir(self.tmp):
            os.unlink(os.path.join(self.tmp, name))
        os.rmdir(self.tmp)

    def _record(self, **overrides):
        record = {
            "pageid": 1,
            "title": "Colosseum",
            "url": "https://en.wikipedia.org/wiki/Colosseum",
            "lat": 41.8902,
            "lon": 12.4922,
            "coord_source": "api",
            "extract": "Amphitheatre",
            "summary": "Amphitheatre in Rome",
            "image": "Colosseo.jpg",
            "image_url": "https://upload.wikimedia.org/x.jpg",
            "infobox": {"built": "80 AD"},
            "categories": ["Category:Colosseum"],
        }
        record.update(overrides)
        return record

    def test_upsert_is_idempotent_and_updates(self):
        with Store(self.db) as store:
            self.assertTrue(store.upsert_page(self._record()))
            self.assertFalse(store.upsert_page(self._record(summary="Updated")))
            self.assertEqual(store.count(), 1)
            self.assertEqual(store.stats()["with_image"], 1)

    def test_visited_tracking_enables_resume(self):
        with Store(self.db) as store:
            store.mark_visited("A")
            self.assertTrue(store.was_visited("A"))
            self.assertFalse(store.was_visited("B"))

    def test_bbox_and_radius_queries(self):
        with Store(self.db) as store:
            store.upsert_page(self._record())
            store.upsert_page(self._record(pageid=2, title="Far", lat=45.0, lon=9.0))
            self.assertEqual(len(store.in_bbox(41, 12, 42, 13)), 1)
            near = store.near(41.8902, 12.4922, radius_km=1)
            self.assertEqual([r["title"] for r in near], ["Colosseum"])
            self.assertLess(near[0]["distance_km"], 0.01)

    def test_photo_join_normalises_file_names(self):
        with Store(self.db) as store:
            store.upsert_page(self._record(image="Colosseo_2013.jpg"))
            store.upsert_photo(
                {
                    "file": "File:Colosseo 2013.jpg",
                    "url": "https://u/x.jpg",
                    "license": "CC BY-SA 4.0",
                    "artist": "Someone",
                }
            )
            self.assertEqual(store.pending_image_files(), [])
            records = list(store._records())
            self.assertEqual(records[0]["photo"]["url"], "https://u/x.jpg")
            self.assertEqual(records[0]["photo"]["license"], "CC BY-SA 4.0")

    def test_pending_images_lists_unresolved(self):
        with Store(self.db) as store:
            store.upsert_page(self._record(image="A.jpg"))
            store.upsert_page(self._record(pageid=2, title="B", image=""))
            self.assertEqual(store.pending_image_files(), ["A.jpg"])

    def test_exports_round_trip(self):
        out = os.path.join(self.tmp, "pages.jsonl")
        csv_out = os.path.join(self.tmp, "pages.csv")
        with Store(self.db) as store:
            store.upsert_page(self._record())
            store.export_jsonl(out)
            store.export_csv(csv_out)
        with open(out, encoding="utf-8") as handle:
            record = json.loads(handle.readline())
        self.assertEqual(record["title"], "Colosseum")
        self.assertEqual(record["infobox"]["built"], "80 AD")
        with open(csv_out, encoding="utf-8") as handle:
            self.assertTrue(handle.readline().startswith("pageid,title"))


if __name__ == "__main__":
    unittest.main()
