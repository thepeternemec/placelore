# Roadmap

Ordered by what unblocks the most people. Everything here is scoped to
**historical places and landmarks** — see [docs/SCOPE.md](docs/SCOPE.md).

## Now (0.3.x)

- [x] Google Places (New) shaped clean layer
- [x] Verified parsing with Google's own protobuf messages
- [x] Wiki place ↔ Google id ↔ photo links, with integrity checks
- [x] Bulk build from Wikidata (`P1435` + `P625`), resumable per country
- [x] Verified, attributable open-data bundle

## Next (0.4)

- [ ] **`overture` importer** — 3.17 M "Cultural and Historic" features from
  Overture, matched by proximity and name, storing GERS IDs alongside Google IDs
- [ ] **`bulk run`** — one command that drains `pending` until zero, with
  progress and a per-country summary
- [ ] **Sharded publish** — bundles under 100 MB with a top-level manifest, so
  releases fit GitHub Releases and static hosting
- [ ] **Category photo fill** — for places with no `P18`, pull one photo from the
  Commons category instead of leaving the place bare

## Later

- [ ] Incremental refresh using `revisions` timestamps and GERS changelogs
- [ ] Parquet export of `places` and `place_photos`
- [ ] Heritage-designation filtering in the crawler (`--heritage`)
- [ ] Country-level coverage report published with each release
- [ ] Optional Nominatim enrichment for coarse locality (not street addresses)

## Explicit non-goals

- Restaurants, shops, hotels, or any business directory
- Opening hours, phone numbers, ratings, live status
- Scraping Google Maps or any service whose terms forbid it
- Rehosting image bytes; the bundle ships URLs and attribution
- A hosted API service — this is a dataset and a build tool, not a platform

## How items leave this list

An item ships when it has tests, documentation, and a changelog entry. Items that
nobody has asked for in six months are moved to "not planned" rather than left to
imply intent.
