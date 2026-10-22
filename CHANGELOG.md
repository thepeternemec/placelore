# Changelog

Format: [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).
Versioning: [Semantic Versioning](https://semver.org/).

## [2.0.0] — 2026-10-22

### Changed

- **Renamed from `wikicrawl` to `placelore`.** The old name described the
  mechanism; this one describes the thing. Breaking for anyone who pinned the
  package: the module, the console script and the repository are all
  `placelore` now. GitHub redirects the old repository URL; old releases stay
  available under the previous name and version.
- README rewritten: what it answers, what it holds, what it is not. Fewer tables,
  no feature inventory.

## [Unreleased]

- `overture` importer for breadth (3.17 M Cultural and Historic features)
- `bulk run` that drains `pending` in one command
- Sharded bundles under 100 MB for static hosting

## [1.1.0] — 2026-10-22

### Added

- **`serve`**: Nearby Search, Text Search and Place Details under Google's paths,
  from a local SQLite file. Honours `X-Goog-FieldMask` including nested paths,
  returns Google's error envelope, caps at 20 nearest-first, and can return linked
  Google ids as `id` with `--prefer-google-ids`.
- **`slim`**: the read-only serving database — provenance, categories, infobox
  JSON and bookkeeping dropped. 940 KB → 300 KB on the sample.
- **`docs/API.md`**: base-URL swap, endpoint support, deliberate differences.

## [1.0.0] — 2026-10-22

### Added

- **`gaps`**: missing photographs, categories, articles, designations,
  attribution and licences, each linked to Wikidata. Markdown and JSON; counts
  complete, rows capped.
- Own section on giving back to Wikimedia in the docs.

### Changed

- Actions bumped to `checkout@v7`, `setup-python@v7`, `action-gh-release@v3`.
- Release workflow builds, installs and imports the wheel before publishing.

## [0.3.0] — 2026-10-21

- **`bulk`**: stage every Wikidata item with `P1435` + `P625` (2,210,883) via
  SPARQL only, then enrich by `P18` in batches of 50. Resumable.
- **`publish`**: bundle with payload, photo index, generated `ATTRIBUTION.md` and
  a Frictionless `datapackage.json` carrying SHA-256 per file.
- **`link`**: `place_links` keeps every Google candidate with method,
  confidence and evidence; one primary per place; import/export/check/promote/remove.
- **`verify`**: parse the payload with `google.maps.places_v1`; enforced in CI.
- Fixed: fabricated `businessStatus`, shared-photo key collision, `zoo` and
  `art_gallery` inference from template noise.

## [0.2.0] — 2026-10-21

- Google Places (New) shaped `places` and `place_photos`, strict serialisers that
  omit unset fields as protobuf JSON does.
- `google-match` with name and distance scoring; only `google_place_id` stored by
  default; `v_google_stale` for refresh.

## [0.1.0] — 2026-10-21

- Polite MediaWiki client: user agent, `maxlag`, `Retry-After`, backoff,
  continuation paging.
- Category, link and geo-grid crawling; resumable SQLite store; Commons
  `imageinfo` with licence and author preserved.
