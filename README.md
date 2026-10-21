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

```sql
pages(pageid PK, title UNIQUE, url, lat, lon, coord_source, extract, summary,
      image, image_url, infobox JSON, fetched_at)
page_categories(pageid, category)
photos(file PK, url, width, height, mime, license, artist, credit, description, description_url)
visited(title PK, source, visited_at)
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

## Roadmap

- [ ] `--wikidata`: attach QID, heritage designation, Commons category per page
- [ ] `--commons-category`: crawl a monument's curated Commons category instead of geosearch
- [ ] `--bbox`: rectangular region sweeps with automatic cell subdivision
- [ ] Incremental mode using `revisions` timestamps
- [ ] Parquet export

## Development

```console
$ make test     # 25 offline tests, no network
$ make lint     # ruff, if installed
```

Tests use a scripted transport, so retries, continuation and the 500-cap logic are all exercised without touching the network.

## License

Code: MIT. Crawled text: CC BY-SA 4.0 via Wikipedia. Images: each file's own licence (commonly CC BY-SA or public domain) — you must keep the attribution string in `photo.artist` and link `photo.page` when you republish.
