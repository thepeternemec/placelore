# Schema

Two layers: `places` is the product, `pages` is provenance. Field names and
enums mirror `places.googleapis.com/v1` (discovery document, revision 20261019),
so a row serialises to a valid Places API response.

## places

| Column | Places API (New) | Source |
| --- | --- | --- |
| `id` | `id` | `wc:<QID>`, else `wc:<wiki>:<pageid>` |
| `name` / `language_code` | `displayName.text` / `.languageCode` | article or Wikidata label |
| `lat` / `lng` | `location.latitude` / `.longitude` | `prop=coordinates` or `P625` |
| `types` | `types` | inferred, word-bounded |
| `primary_type` | `primaryType` | first inferred type |
| `formatted_address`, `website_uri`, `rating`, `user_rating_count` | same names | **Google only**, time-limited |
| `business_status` | `businessStatus` | `NULL` unless Google said |
| `google_place_id` | — | durable join key, cache of the primary link |
| `wikidata_id`, `wikipedia_url` | — | provenance |
| `heritage_designations` | — | JSON array of `P1435` QIDs |

Unset values are omitted from the payload, as protobuf JSON does: no Google
address means no `formattedAddress` key, not `null`.

## place_photos

`(place_id, id)` primary key, so one Commons file can illustrate several places.
`name` is a resource name `places/<place id>/photos/<slug>`; `url`, `license`,
`author_name` and `author_uri` are what attribution needs. Google's `Photo`
message has no URL field, which is why URLs live in `photos.json` instead of the
payload.

## place_links

`(place_id, google_place_id)` with `is_primary`, `method`, `confidence`,
`evidence` and `verified`. One primary per place, enforced by a partial unique
index; every rejected candidate is kept as evidence. `link check` proves the
cache on `places` still mirrors the primary link.

## Types

Only strings from Google's published type tables are emitted — 341 Table A plus
178 Table B types, with the vocabulary tested against that list. Matching is
word-bounded and ignores template plumbing, after the first crawl labelled an
arch a `zoo` (from `mapframe-zoom`) and an `art_gallery` (from a maintenance
category). `bridge` is Table B: valid in `types`, rejected by Nearby
`includedTypes`, so `nearby_types()` filters it out.

## Bulk staging

`wd_places(qid PK, label, lat, lon, enwiki_title, image_file, commons_category,
heritage JSON, country, status, place_id)` moves `pending → enriched`. Items with
several `P1435` values arrive as several SPARQL solutions and are merged by QID.
Bulk places are written with `id = 'wc:' || qid` because Wikidata is the source.

## Storage

`datapackage.json` in a published bundle declares types, row counts and a SHA-256
per file. `slim` keeps only the columns an endpoint can return.
