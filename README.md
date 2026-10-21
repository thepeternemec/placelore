# wikicrawl

[![ci](https://github.com/thepeternemec/wikipedia-crawl/actions/workflows/ci.yml/badge.svg)](https://github.com/thepeternemec/wikipedia-crawl/actions/workflows/ci.yml)
[![license: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)

An open dataset of historical places — coordinates, descriptions and photographs — built from Wikimedia, keyed to Google place IDs, and stored in one SQLite file you own.

The point is to stop paying per request for facts the world already contributed for free.

## The migration

Most apps that show places today are built on a per-request API: Nearby Search
for the list, Place Details for the photo, repeated for every user and every
pan of the map. That works until it doesn't — the bill scales with traffic, and
the terms stop you keeping what you fetched, so you can never amortise it.

This project inverts that. The place details and the photographs are migrated
onto Wikimedia's open storage, where they already exist, were reviewed by
volunteers, and carry licences that permit redistribution. Google is reduced to
what it is uniquely good at: a stable identifier.

| | Before | After |
|---|---|---|
| List of nearby places | Nearby Search, per request | own SQLite, per query |
| Place details, photos | Place Details, per place | Wikimedia + Commons, one bulk pass |
| Data ownership | cannot cache beyond limits | yours, CC BY-SA / per-file |
| Serving cost | scales with traffic | zero |
| Google dependency | every request | one ID column, optional |

The serving cost goes to zero because the database is local. What remains is a
**one-time join**: to attach Google place IDs you either spend one Text Search
call per place you care about, or import IDs you already hold
(`link import`). Matching all 2.2 M places is itself 2.2 M billed calls, so match
the subset you actually serve — the schema is built for partial coverage, with
`unlinked` visible rather than implied.

### What this is not

Honest boundaries, because a dataset that oversells itself is worse than none:

- **Not a Places API replacement where Google's own data matters** — opening
  hours, phone numbers, ratings, live business status and structured street
  addresses do not exist in Wikimedia and are not invented here.
- **Not Google photos.** Every image is a Commons file with its own licence and
  author; nothing is fetched from Google.
- **Not a free pass on terms.** Storing `place_id` is permitted; storing the rest
  of a Places response is not. The schema enforces that distinction instead of
  ignoring it.
- **Not a claim that Wikimedia is complete.** Coverage tracks volunteer effort,
  which is uneven by country and topic.

Being open is a design requirement, not a slogan: the content needs no API key,
the build is reproducible from a checkout, and `wikicrawl publish` writes a
bundle anyone can verify and redistribute. See
[DATA-LICENSE.md](DATA-LICENSE.md) for the exact split of rights.

## What you get

- **Three crawl strategies** — category trees, link graphs, and geo grids that survive the API's 500-result cap.
- **One SQLite file** with provenance and product layers kept separate.
- **Stable ids** — `wc:Q10285` where Wikidata knows the place, `wc:enwiki:27119` otherwise.
- **A Google-shaped payload** that parses with Google's own protobuf messages, verified in CI.
- **An explicit link chain** — wiki place → Google id → photos, with method, confidence and evidence per link.
- **No dependencies** beyond the Python standard library.

## Quickstart

```console
$ git clone https://github.com/thepeternemec/wikipedia-crawl
$ cd wikipedia-crawl
$ python3 -m wikicrawl collect --lat 41.8902 --lon 12.4922 --radius 500 --cell 100 --db rome.sqlite
$ python3 -m wikicrawl photos  --db rome.sqlite
$ python3 -m wikicrawl normalize --db rome.sqlite
$ python3 -m wikicrawl export --db rome.sqlite --format google --out places.json
```

`python3 -m wikicrawl` needs nothing but the standard library. Installing the `wikicrawl` command instead:

```console
$ python3 -m pip install -e .
```

Installing needs `pip >= 22` / `setuptools >= 61` (PEP 621 metadata). On an older toolchain — macOS's bundled Python ships setuptools 58 — use the module form above.

Set a real contact in your user agent; Wikimedia's policy requires it:

```console
$ python3 -m wikicrawl collect --category "Category:Colosseum" \
    --user-agent "my-project/0.1 (https://github.com/you/my-project; you@example.org)"
```

## Three ways to crawl

**By category tree** — walks `categorymembers`, following subcategories up to `--depth`, cycle-safe.

```console
$ python3 -m wikicrawl collect --category "Category:Cultural heritage monuments in Slovenia" \
    --depth 2 --limit 500 --db slovenia.sqlite
```

**By geography** — overlays a grid so the 500-result cap cannot truncate a dense centre, and says so when a cell still hits it.

```console
$ python3 -m wikicrawl collect --lat 41.8902 --lon 12.4922 --radius 400 --cell 100 --db rome.sqlite
geo: 87 pages in 45 cells @100m
```

**By link graph** — breadth-first from seed articles.

```console
$ python3 -m wikicrawl collect --seed "Colosseum" --depth 1 --limit 200 --db rome.sqlite
```

## The two layers

```sql
-- product: Google-shaped
places(id PK, name, lat, lng, types, primary_type, formatted_address,
       google_place_id, google_fetched_at, wikidata_id, ...)
place_photos(place_id, id, name, url, width_px, height_px,
             author_name, author_uri, license, PRIMARY KEY(place_id, id))
place_links(place_id, google_place_id, is_primary, method, confidence,
            evidence, verified, PRIMARY KEY(place_id, google_place_id))

-- provenance: what the wiki said
pages(pageid PK, title, url, lat, lon, extract, summary, infobox, image)
page_categories(pageid, category)
photos(file PK, url, width, height, license, artist, description_url)
```

Full field mapping against the Places API (New) messages: [SCHEMA.md](SCHEMA.md).

`place_links` keeps every candidate, not just the winner — a rejected match is evidence, and one place legitimately mapping to two Google records is a real case. Exactly one row per place is primary, enforced by a partial unique index; `places.google_place_id` is only a cache of it, and `link check` proves the two agree.

## Linking to Google

```console
$ python3 -m wikicrawl google-match --db rome.sqlite --dry-run --limit 20   # no quota spent
$ python3 -m wikicrawl google-match --db rome.sqlite --limit 20             # needs GOOGLE_MAPS_API_KEY
$ python3 -m wikicrawl link import --db rome.sqlite --file google_ids.csv   # ids you already have
$ python3 -m wikicrawl link check  --db rome.sqlite
$ python3 -m wikicrawl link stats  --db rome.sqlite
$ python3 -m wikicrawl export --db rome.sqlite --format links --out links.json
```

Matching is Text Search biased to a 500 m circle, scored `0.7 × name similarity + 0.3 × proximity`, accepted at ≥ 0.55. Only `google_place_id` is stored by default, because that is the only field the terms let you keep. `--store-fields` opts into caching addresses, and `v_google_stale` lists rows older than the refresh window.

`links.json` is the explicit chain — wiki place id → Google place id → photos with URL, licence and author, plus an `unlinked` list so gaps are stated rather than implied.

## The payload parses with Google's code

Shape claims are cheap, so the repo checks its own output with `google.maps.places_v1`, the generated messages their Python client uses:

```console
$ python3 -m pip install google-maps-places     # optional, only for checking
$ python3 -m wikicrawl verify --file places.json --photo-index photos.json
parsed 45/45 places with google.maps.places_v1
envelope: SearchTextResponse + SearchNearbyResponse
OK
```

`export --format google --verify` runs the same check at write time and exits 1 on rejection. CI runs it on every push, so the guarantee cannot rot.

Parsing is not resolution: Google's parser accepts our ids because `id` is a string, but Google's servers will not resolve `wc:enwiki:553500`. Only `google_place_id` — filled by `google-match` — is resolvable at Google.

## Dataset size, measured

A 500 m crawl of central Rome, as shipped:

| Item | Size |
|---|---|
| SQLite database | 348 KiB = 356,352 bytes (87 pages × 4 KiB) |
| `places.json` | 30 KB pretty, 19 KB compact |
| `photos.json` | 17 KB |
| Rows | 45 places · 43 photos · 723 category links |

That is **7,919 bytes per place** (7.7 KiB): 2.5 KiB page text (extract, summary, infobox), 2.0 KiB categories (16 per page), 0.7 KiB Commons photo metadata, 0.6 KiB photo rows, 0.6 KiB place rows and indexes, 0.2 KiB bookkeeping. Wikitext is deliberately not stored.

Against the 2,210,883 coordinate-bearing heritage items in Wikidata (projections in decimal GB, as storage is billed):

| Places | SQLite | JSON pretty | JSON compact |
|---|---|---|---|
| 1,000 | 7.9 MB | 0.7 MB | 0.4 MB |
| 100,000 | 0.8 GB | 68 MB | 43 MB |
| 2,210,883 | 17.5 GB | 1.5 GB | 0.9 GB |

Storage is not the constraint:

1. **Images dominate.** URLs cost nothing; 2.2 M originals at 1.5–3 MB are 3–6 TB, before thumbnails.
2. **~40% of the database is avoidable.** Categories and the duplicated extract/summary pair can go for a production build, landing near 5 KiB/place (~11 GB).
3. **Discovery is the real cost.** Enrichment is arithmetic: 20 titles per request → 110,544 requests, ~6 h minimum at 0.2 s each; Commons photos add ~44 k. But a 100 m geo grid cannot cover the world — the workable route is a place list from Wikidata/QLever plus the `geo_tags` dump (768 MB) for the Commons side, with the grid reserved for gap-filling.

## All places: the bulk build

Grid crawling covers a city. The world comes from Wikidata: every item with a
heritage designation (`P1435`) and coordinates (`P625`) — 2,210,883 of them.

Two phases, so the expensive work happens once per place and can be interrupted:

```console
$ python3 -m wikicrawl bulk fetch  --db world.sqlite --country Q215        # one country
$ python3 -m wikicrawl bulk fetch  --db world.sqlite --all-countries      # everything
$ python3 -m wikicrawl bulk status --db world.sqlite
staged     1500
pending    1200
enriched   300
places     300
photos     213

$ python3 -m wikicrawl bulk enrich --db world.sqlite --limit 300
$ python3 -m wikicrawl export --db world.sqlite --format google --out world.json
```

`fetch` is SPARQL only — no per-place API calls — and writes to a staging table
`wd_places`. `enrich` resolves each row's `P18` commons image in batches of 50
and writes clean `places` rows with id `wc:Q…`. Both are resumable: re-running
skips what is already staged or enriched, so a run that dies at 60% continues.

Measured on 1,500 Slovenian heritage items: **5 requests, 5 seconds** to stage;
**300 places → 213 photos in 3.5 seconds** to enrich, with 71% of places having a
usable `P18` photograph.

Full-world estimate at default politeness:

| Phase | Requests | Time |
|---|---|---|
| Stage the list (~4,400 pages of 500) | ~4,400 | ~1 h |
| Resolve `P18` images (~44,000 pages of 50) | ~44,000 | ~2.5 h |
| Write `places` + `place_photos` | 0 | minutes |

`--limit` makes any of it a sample, and `--dry-run` prints the SPARQL without
sending it.

Photos come from `P18`, not from Commons categories: one request per fifty
places instead of one per place. Items without a `P18` still land in the database
with their category recorded, so a later pass can fill the gap selectively
instead of paying for every place.

## Publishing an open bundle

A database on your machine is not an open dataset. `publish` writes a directory
someone else can download, verify and redistribute:

```console
$ python3 -m wikicrawl publish --db world.sqlite --out dist/slovenia --name wikicrawl-slovenia
bundle: dist/slovenia
  places 500  photos 377  links 0
  places.jsonl          500 rows  sha256:24fb2c3f5039...
  places.json           500 rows  sha256:6334bf9ae955...
  photos.json           377 rows  sha256:b41d2f868316...
  links.json              0 rows  sha256:2d18a2510da6...
```

| File | What |
|---|---|
| `places.jsonl` | one place per line, Places API (New) shape |
| `places.json` | the same wrapped as a search response |
| `photos.json` | photo resource name → URL, licence, author |
| `links.json` | wiki place id → Google place id |
| `ATTRIBUTION.md` | one line per photograph: resource name, file, author, licence, source |
| `datapackage.json` | Frictionless descriptor: counts, SHA-256 per file, licences, field types |
| `README.md` | what the bundle is, in plain language |

The 500-place Slovenia bundle is 896 KB, of which `ATTRIBUTION.md` is 128 KB —
attribution is the second-largest file in an honest open dataset, behind the
payload itself, and that is the point.
Every photo resource name in `places.jsonl` resolves in `photos.json` and appears
in `ATTRIBUTION.md`; a test enforces both.

## Politeness

* 0.2 s between requests by default (`--min-interval`), per client.
* `maxlag=5` on every request, exponential backoff when the server objects.
* `Retry-After` honoured on 429/503.
* Category, link and extract listings page through `continue` tokens instead of assuming one page.
* `action=query` only — no HTML scraping.

For bulk image downloads use the [Wikimedia dumps](https://dumps.wikimedia.org/), not the API.

## Limits

* **English Wikipedia by default.** Point `--api-url` at another wiki for other languages.
* **Grid coverage is bounded by cell size.** The crawler reports cells that capped; it cannot recover rows the API already dropped.
* **One coordinate per place**, so large sites collapse to a point.
* **Infobox parsing is heuristic.** Nested templates and `{{convert}}` are handled; exotic ones are not.
* **Matching is heuristic.** Famous places link cleanly; dense old towns with near-identical names want `--threshold 0.7` and a look at `google_matches`.
* **Grid crawling has no heritage filter** — for that, use `bulk`, where the criterion is `P1435` by definition.
* **Bulk types are coarse.** With only a label and a Commons category to work from, most non-church heritage items infer as `tourist_attraction`; the designation itself is kept in `heritage_designations` rather than mapped onto Google's vocabulary.

## Roadmap

- [x] Google Places (New) compatible clean layer, matching and export
- [x] Verified parsing with Google's own protobuf messages
- [x] First-class wiki place ↔ Google id ↔ photo links
- [ ] `--wikidata`: attach QID, heritage designation (`P1435`), Commons category per page
- [ ] `--commons-category`: crawl a monument's curated Commons category instead of geosearch
- [ ] `--bbox`: rectangular sweeps with automatic cell subdivision
- [x] Bulk mode: build the place list from Wikidata/QLever, enrich by `P18`
- [ ] Parquet export

## Development

```console
$ make test            # 117 tests, no network (6 need the optional Google client)
$ make verify-google   # parse the fixture with Google's protobufs
$ make lint            # ruff, if installed
```

Tests use a scripted transport, so retries, continuation and the 500-cap logic are exercised without touching the network.

## Licence

Code: MIT. Text and descriptions: CC BY-SA 4.0 from Wikipedia. Photographs: each
file's own licence, attributed per file. Google place IDs: stored under Google's
terms, which permit indefinite storage of that field. Fields this project
generates (`wc:` ids, inferred types, match scores) are released CC0, as is the
compilation to the extent we hold any rights in it.

The full split, including what share-alike does and does not cover, is in
[DATA-LICENSE.md](DATA-LICENSE.md).

If you build on this dataset, the honest attribution is: content by Wikimedia
contributors, place identifiers by Google, schema by this project.
