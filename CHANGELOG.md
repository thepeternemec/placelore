# Changelog

All notable changes are recorded here. Format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/); the project follows
[Semantic Versioning](https://semver.org/).

## [Unreleased]

### Planned

- `overture` importer: breadth from Overture's Cultural and Historic category
- Resumable `bulk run` that drains `pending` in one command
- Sharded bundle output for hosts with a 100 MB file limit

## [0.3.0] — 2026-10-21

The release that makes "all places" and "open for everyone" mean something
checkable.

### Added

- **`bulk` pipeline**: `fetch` stages every Wikidata item with a heritage
  designation (`P1435`) and coordinates (`P625`) — 2,210,883 of them — using
  SPARQL only; `enrich` resolves `P18` images in batches of 50 and writes places
  with id `wc:Q…`. Both phases are resumable.
- **`publish`**: writes a redistributable bundle — `places.jsonl`, `places.json`,
  `photos.json`, `links.json`, a generated `ATTRIBUTION.md`, and a Frictionless
  `datapackage.json` with row counts and SHA-256 per file.
- **`link`**: `place_links` records every Google candidate with method,
  confidence and evidence, enforces a single primary per place, and supports
  `import`, `export`, `check`, `stats`, `promote` and `remove`.
- **`verify`** and `export --verify`: parse a payload with
  `google.maps.places_v1`, Google's own generated messages. CI runs it.
- **`DATA-LICENSE.md`**: explicit split of MIT code, CC BY-SA text, per-file
  photographs, Google's identifiers under Google's terms, and CC0 for the fields
  and compilation rights this project contributes.
- **`docs/SCOPE.md`**: historical places and landmarks only, with the reasons.
- Governance, code of conduct, security policy, issue and pull request templates,
  CodeQL and Dependabot configuration.

### Changed

- README now states the migration thesis (serving cost → zero, one-time join
  cost → scoped) instead of describing only the crawler.
- `normalize` warns before `--rebuild` drops Google links.

### Fixed

- `businessStatus` was fabricated as `OPERATIONAL` on every row; it is now `NULL`
  unless a Places response sets it.
- A Commons file used by two places silently moved between them; the photo key is
  now `(place_id, id)`.
- Type inference produced `zoo` from `mapframe-zoom` and `art_gallery` from a
  maintenance category; matching is now word-bounded and ignores template
  plumbing.
- `row_factory` assumptions in `bulk status` and reserved-word SQL aliases.

### Data

- 500 Slovenian heritage places, 377 photographs, published as a verified bundle
  (896 KB, 128 KB of which is attribution).

## [0.2.0] — 2026-10-21

### Added

- Google Places (New) shaped clean layer: `places`, `place_photos`, strict
  serialisers that omit unset fields as protobuf JSON does.
- `normalize` to build it from crawl provenance; `export --format google`.
- `google-match` with name-similarity and distance scoring, storing only
  `google_place_id` by default.
- `v_google_stale` for Google-sourced fields past the refresh window.

### Fixed

- Shared lead images colliding on the photo primary key.

## [0.1.0] — 2026-10-21

### Added

- Polite MediaWiki client: user agent requirement, `maxlag`, `Retry-After`,
  exponential backoff, continuation paging.
- Three crawl strategies: category trees, link graphs, and geo grids that survive
  the 500-result cap.
- SQLite store with resumable `visited` tracking, JSONL and CSV export.
- Commons `imageinfo` enrichment with licence and author preserved.
- 25 offline tests with a scripted transport.

[Unreleased]: https://github.com/thepeternemec/wikipedia-crawl/compare/v0.3.0...HEAD
[0.3.0]: https://github.com/thepeternemec/wikipedia-crawl/releases/tag/v0.3.0
[0.2.0]: https://github.com/thepeternemec/wikipedia-crawl/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/thepeternemec/wikipedia-crawl/releases/tag/v0.1.0
