# wikicrawl

[![ci](https://github.com/thepeternemec/wikipedia-crawl/actions/workflows/ci.yml/badge.svg)](https://github.com/thepeternemec/wikipedia-crawl/actions/workflows/ci.yml)
[![license: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)

A small, polite, resumable crawler for **Wikipedia places, their coordinates, and their photos** — one SQLite file, zero dependencies, Python 3.9+.

Wikipedia's API is easy to call and surprisingly easy to get wrong: result lists truncate silently, some parameters are illegal in combination, and rate limits arrive as `maxlag` errors rather than HTTP failures. This project encodes those rules so a crawl is complete, restartable, and doesn't get you blocked.

```console
$ wikicrawl collect --category "Category:Colosseum" --depth 1 --db rome.sqlite
$ wikicrawl photos --db rome.sqlite
$ wikicrawl stats --db rome.sqlite
pages        12
with coords  6
with image   6
with infobox 12
photos       6
```

## Why this exists

Harvesting "all historical places" means joining three Wikimedia surfaces:

| Surface | What it gives you | Trap |
| --- | --- | --- |
| Wikipedia | Articles, coordinates, infobox fields | `prop=extracts` accepts only 20 titles per request; `rvlimit` is illegal with multiple titles |
| Commons | Upload URLs, pixel sizes, licences, authors | `geosearch` caps at 500 results with **no continuation token** |
| Wikidata | Stable place IDs, heritage designation | Optional in v0.1, see roadmap |

A crawler that ignores the first and third traps silently returns partial data — which is worse than failing, because you won't notice.

## Install

No dependencies. From a checkout:

```console
$ git clone https://github.com/thepeternemec/wikipedia-crawl
$ cd wikipedia-crawl
$ python3 -m wikicrawl --help
```

Or install the `wikicrawl` command:

```console
$ python3 -m pip install -e .
$ wikicrawl --help
```

Installing needs `pip >= 22` / `setuptools >= 61` (i.e. PEP 621 metadata support). On an older toolchain — macOS's bundled Python ships setuptools 58 — use `python3 -m wikicrawl` from the checkout instead; it needs nothing but the standard library.

Set a real contact in your user agent — Wikimedia's policy requires it, and it is the difference between being throttled and being blocked:

```console
$ wikicrawl collect --category "Category:Colosseum" \
    --user-agent "my-project/0.1 (https://github.com/you/my-project; you@example.org)"
```

## Three ways to crawl

**By category tree.** Walks `categorymembers`, following subcategories up to `--depth` hops. Cycles are handled.

```console
$ wikicrawl collect --category "Category:Cultural heritage monuments in Slovenia" \
    --depth 2 --limit 500 --db slovenia.sqlite
```

**By geography.** Overlays a grid of cells and queries each one, so the 500-result cap cannot truncate a dense city centre. Reports any cell that still hit the cap.

```console
$ wikicrawl collect --lat 41.8902 --lon 12.4922 --radius 400 --cell 100 --db rome.sqlite
geo: 87 pages in 45 cells @100m
```

Shrink `--cell` (60–100 m works for dense historic centres) until the warning disappears. The grid prints `[WARNING: N cells hit the 500 cap ...]` when coverage is incomplete.

**By link graph.** Breadth-first over internal links from seed articles.

```console
$ wikicrawl collect --seed "Colosseum" --depth 1 --limit 200 --db rome.sqlite
```

## Clean, Google-shaped output

After crawling, `normalize` builds the product layer: one row per place with
Places API (New) field names, stable ids, and photos that keep their licence and
attribution. The crawl tables stay behind as provenance.

```console
$ wikicrawl normalize --db rome.sqlite
places=87 photos=61 skipped=12 duplicates=3
$ wikicrawl export --db rome.sqlite --format google --out places.json
$ wikicrawl export --db rome.sqlite --format photo-index --out photos.json
```

`places.json` is a strict `{"places": [...]}` payload — the same envelope as
Nearby/Text Search — so code written against the Places API can parse it
unchanged:

```json
{"places": [{
  "id": "wc:enwiki:553500",
  "types": ["historical_landmark"],
  "displayName": {"text": "Arch of Constantine", "languageCode": "en"},
  "location": {"latitude": 41.88972, "longitude": 12.49083},
  "primaryType": "historical_landmark",
  "businessStatus": "OPERATIONAL",
  "photos": [{"name": "places/wc:enwiki:553500/photos/commons-arch-of-constantine-rome-south-side",
              "widthPx": 6272, "heightPx": 5292,
              "authorAttributions": [{"displayName": "NikonZ7II (Paris Orlando)",
                                      "uri": "https://commons.wikimedia.org/wiki/User:NikonZ7II"}]}]
}]}
```

Image URLs live in `photos.json`, keyed by photo `name`, because Google's
`Photo` message has no URL field — mixing them in would break the shape.

Linking to Google itself is one command, and `--dry-run` shows the searches
before spending quota:

```console
$ wikicrawl google-match --db rome.sqlite --dry-run --limit 20
$ wikicrawl google-match --db rome.sqlite --limit 20 --threshold 0.6
```

Only `google_place_id` is stored by default, because Google's terms permit
storing place IDs indefinitely but not other Place content. `--store-fields`
opts into caching addresses too, and `v_google_stale` then lists what has aged
past the refresh window. See [SCHEMA.md](SCHEMA.md) for the full mapping.

## Enrich and export

```console
$ wikicrawl photos --db rome.sqlite          # Commons imageinfo: URL, size, licence, author
$ wikicrawl export --db rome.sqlite --out places.jsonl
$ wikicrawl export --db rome.sqlite --out places.csv --format csv
$ wikicrawl near --db rome.sqlite --lat 41.8902 --lon 12.4922 --radius-km 1
  0.011 km  Colosseum                             https://en.wikipedia.org/wiki/Colosseum
  0.148 km  Colosseo (Rome Metro)                 https://en.wikipedia.org/wiki/Colosseo_(Rome_Metro)
```

An exported record:

```json
{
  "pageid": 27119,
  "title": "Colosseum",
  "url": "https://en.wikipedia.org/wiki/Colosseum",
  "lat": 41.8902,
  "lon": 12.4922,
  "summary": "The Colosseum is an elliptical amphitheatre in the centre of the city of Rome, Italy.",
  "infobox": {"built": "80 AD", "height": "48 m"},
  "categories": ["Category:Colosseum", "Category:Ancient Roman amphitheatres"],
  "photo": {
    "url": "https://upload.wikimedia.org/wikipedia/commons/d/de/Colosseo_2020.jpg",
    "width": 6000,
    "height": 4000,
    "license": "CC BY-SA 4.0",
    "artist": "Example Photographer",
    "page": "https://commons.wikimedia.org/wiki/File:Colosseo_2020.jpg"
  }
}
```

## Resumable by design

Every visited title is recorded in the `visited` table and page records upsert on `pageid`. Re-running the same command continues where it stopped:

```console
$ wikicrawl collect --category "Category:Colosseum" --depth 3 --db rome.sqlite
$ # interrupted with Ctrl-C
$ wikicrawl collect --category "Category:Colosseum" --depth 3 --db rome.sqlite
```

Use `--force` to re-fetch pages that were already visited (for example after a parser fix).

## Data model

Two layers: provenance, and product.

```sql
-- product (Google Places shape)
places(id PK, name, display_name, lat, lng, types JSON, primary_type,
       formatted_address, website_uri, rating, google_place_id UNIQUE,
       google_fetched_at, match_confidence, wikidata_id, source, ...)
place_photos(id PK, place_id, name, url, width_px, height_px, author_name,
             author_uri, license, position)

-- provenance (what the wiki said)
pages(pageid PK, title UNIQUE, url, lat, lon, image, infobox JSON, fetched_at)
page_categories(pageid, category)
photos(file PK, url, width, height, license, artist, description_url)
visited(title PK, source, visited_at)

-- audit
google_matches(place_id, google_place_id, score, method, query, matched_at)
```

`lat`/`lon` come from `prop=coordinates`, so they are the article's *primary* coordinate, not a regex over wikitext. File names are normalised (underscores → spaces, first letter case) before joining `pages.image` to `photos.file`, because pageimages and Commons disagree often enough to break naive joins.

## Politeness

* Default 0.2 s between requests (`--min-interval`), per client.
* `maxlag=5` on every request, with exponential backoff when the server complains.
* `Retry-After` honoured on 429/503.
* Category, link and extract requests page through `continue` tokens rather than assuming one page.
* Requests go to `action=query` only — no HTML scraping.

Run one crawl at a time per project. If you need bulk image downloads, use the [Wikimedia dumps](https://dumps.wikimedia.org/) instead of the API; the Commons `geo_tags` table and `page` table are the supported route for worldwide coverage.

## Limits and known gaps

* **English Wikipedia by default.** Point `--api-url` at another wiki for other languages.
* **Grid coverage is bounded by the cell size**, not guaranteed. The crawler tells you when a cell capped; it cannot recover rows the API already dropped.
* **Coordinates are the article's, not the subject's bounding box.** Large sites collapse to one point.
* **Infobox parsing is heuristic.** Nested templates and `{{convert}}` are handled; exotic templates are not.
* **No Wikidata or Commons-category crawling yet** (see roadmap). Heritage filtering (`P1435`), Wiki Loves Monuments IDs and per-monument category photo sets are the next step.
* **Google matching is heuristic.** Name similarity plus distance links most famous places; ambiguous names in dense old towns need a higher `--threshold` and manual review via `google_matches`.
* **No API key is shipped, and none is needed** for crawling. `google-match` is the only command that spends Google quota.

## Roadmap

- [x] Google Places (New) compatible clean layer, matching and export
- [ ] `--wikidata`: attach QID, heritage designation, Commons category per page
- [ ] `--commons-category`: crawl a monument's curated Commons category instead of geosearch
- [ ] `--bbox`: rectangular region sweeps with automatic cell subdivision
- [ ] Incremental mode using `revisions` timestamps
- [ ] Parquet export

## Development

```console
$ make test     # 58 offline tests, no network
$ make lint     # ruff, if installed
```

Tests use a scripted transport, so retries, continuation and the 500-cap logic are all exercised without touching the network.

## License

Code: MIT. Crawled text: CC BY-SA 4.0 via Wikipedia. Images: each file's own licence (commonly CC BY-SA or public domain) — you must keep the attribution string in `photo.artist` and link `photo.page` when you republish.
