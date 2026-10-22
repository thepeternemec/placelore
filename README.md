# wikicrawl

[![ci](https://github.com/thepeternemec/wikipedia-crawl/actions/workflows/ci.yml/badge.svg)](https://github.com/thepeternemec/wikipedia-crawl/actions/workflows/ci.yml)
[![code: MIT](https://img.shields.io/badge/code-MIT-blue.svg)](LICENSE)
[![data: CC BY-SA](https://img.shields.io/badge/data-CC%20BY--SA%204.0-lightgrey.svg)](DATA-LICENSE.md)

Historical places and landmarks — coordinates, descriptions and photographs —
from Wikimedia, keyed to Google place IDs, in one SQLite file you own.

A place should not cost money to display. Google's Places API bills per request
and forbids keeping what you fetched; Wikimedia already hosts the facts and the
photographs under licences that allow redistribution. This project builds that
database, and serves it in the protocol your app already speaks.

## Quickstart

```console
$ git clone https://github.com/thepeternemec/wikipedia-crawl && cd wikipedia-crawl
$ python3 -m wikicrawl bulk fetch  --db world.sqlite --country Q215
$ python3 -m wikicrawl bulk enrich --db world.sqlite --limit 500
$ python3 -m wikicrawl export --db world.sqlite --format google --out places.json
$ python3 -m wikicrawl serve  --db world.sqlite --port 8080
```

Standard library only, Python 3.9+. No API key needed to build or serve.

## Serve the protocol, not a new one

`serve` answers Google's endpoints from your database, so a client changes one
constant and keeps its parser:

```js
const BASE = "http://127.0.0.1:8080";   // was https://places.googleapis.com
```

| Endpoint | Google equivalent |
| --- | --- |
| `POST /v1/places:searchNearby` | Nearby Search (New) |
| `POST /v1/places:searchText` | Text Search (New) |
| `GET /v1/places/{id}` | Place Details (New) |

`X-Goog-FieldMask` is honoured down to nested paths, errors use Google's
envelope, results are capped at 20 nearest-first. `--prefer-google-ids` returns
`google_place_id` as `id` where a link exists. Details and deliberate differences
are in [docs/API.md](docs/API.md).

```console
$ python3 -m wikicrawl slim --db world.sqlite --out serve.sqlite   # 940 KB → 300 KB
```

## Build the dataset

| Command | What it does |
| --- | --- |
| `collect` | crawl by category, links, or a geo grid that survives the 500-result cap |
| `bulk` | stage every Wikidata item with `P1435` + `P625` (2.2 M), then enrich by `P18` |
| `photos` | resolve Commons images to URLs, licences and authors |
| `normalize` | build the clean, Google-shaped `places` layer |
| `link` | attach Google place IDs, with method, confidence and evidence |
| `gaps` | list what is missing upstream, linked to Wikidata |
| `publish` | write a verifiable bundle: payload, photos, attribution, SHA-256 |
| `verify` | parse the payload with `google.maps.places_v1` |

Measured on the 500-place Slovenia sample: **940 KB database**, 377 photographs,
300 KB slimmed for serving. A 500 m crawl of central Rome is 45 places in 348 KB.

## What you get

- **Stable ids** — `wc:Q10285` where Wikidata knows the place, `wc:enwiki:27119`
  otherwise; Google ids stay separate and optional.
- **Photos with provenance** — every image keeps its licence, author and source
  link, because CC BY-SA requires it.
- **An honest bundle** — `datapackage.json` with a SHA-256 per file, and an
  `ATTRIBUTION.md` that is 14% of the download.

## Scope

Heritage, monuments, landmarks. Not restaurants, opening hours, phone numbers or
ratings: they churn, they are commercial, and Wikimedia does not track them.
Wrong coverage would be worse than narrow coverage.

Wikimedia coverage is uneven by country, and the tool never writes upstream —
`gaps` produces work for human editors instead. See
[CONTRIBUTING.md](CONTRIBUTING.md).

## Docs

| | |
| --- | --- |
| [docs/API.md](docs/API.md) | served protocol, field masks, differences |
| [SCHEMA.md](SCHEMA.md) | field mapping to Places API (New) |
| [DATA-LICENSE.md](DATA-LICENSE.md) | what you may do with the data |
| [CONTRIBUTING.md](CONTRIBUTING.md) | setup, rules, scope, fixes upstream |
| [SECURITY.md](SECURITY.md) | private reporting, secrets |
| [CHANGELOG.md](CHANGELOG.md) | what shipped |

## Licence

Code MIT. Text CC BY-SA 4.0 from Wikipedia. Photographs per file, attributed.
Google place IDs under Google's terms, which permit storing that field
indefinitely. Fields this project generates are CC0.

If you build on this: content by Wikimedia contributors, identifiers by Google,
schema by this project.
