# The clean layer: Places API (New) compatible

`places` and `place_photos` are the product. `pages` and `photos` remain as
provenance — what a wiki said, kept so every clean row can be audited back to
its source.

Field names, types and enums mirror `places.googleapis.com/v1`, taken from
Google's discovery document
(`https://places.googleapis.com/$discovery/rest?version=v1`, revision
20261019).

## Field mapping

| Our column | Places API (New) JSON | Where it comes from |
| --- | --- | --- |
| `id` | `id` | `wc:<QID>`, else `wc:<wiki>:<pageid>` |
| `name` | `displayName.text` | article title |
| `language_code` | `displayName.languageCode` | wiki language (default `en`) |
| `lat`, `lng` | `location.latitude`, `location.longitude` | `prop=coordinates` |
| `types` | `types` | inferred from categories, see below |
| `primary_type` | `primaryType` | first inferred type |
| `formatted_address` | `formattedAddress` | **Google only** — null until matched |
| `website_uri` | `websiteUri` | **Google only** |
| `google_maps_uri` | `googleMapsUri` | **Google only** |
| `rating` | `rating` | **Google only** |
| `user_rating_count` | `userRatingCount` | **Google only** |
| `business_status` | `businessStatus` | `OPERATIONAL` by default |
| `place_photos.name` | `photos[].name` | `places/<place id>/photos/<slug>` |
| `place_photos.width_px` / `height_px` | `photos[].widthPx` / `heightPx` | Commons `imageinfo` |
| `place_photos.author_name` / `author_uri` | `photos[].authorAttributions[]` | Commons artist field |

Unset values are **omitted**, exactly as protobuf JSON does: a place with no
Google address has no `formattedAddress` key rather than `null`.

## Identifiers

```
wc:Q10285            # Wikidata item, preferred: survives renames and merges
wc:enwiki:27119      # fallback: stable for the life of that page
```

Both are namespaced so they can never be confused with a Google `ChIJ…` id.
`google_place_id` is a separate, nullable, `UNIQUE` column.

Photo references follow Google's resource shape:

```
places/wc:Q10285/photos/commons-colosseo-2020
```

That shape is structural, not a claim to a Google resource: `google_photo_reference`
stays `NULL` until a real match supplies one, and the URL that actually serves
the bytes lives in the sidecar index, because Google's `Photo` message has no
URL field. Keeping URLs out of the payload is what lets the payload parse.

## Types

Google rejects unknown type strings, so inference is constrained to
`GOOGLE_TYPES` and matched with word boundaries plus an optional plural:

- `mapframe-zoom` must not yield `zoo`
- `Category:Pages using gallery without…` must not yield `art_gallery`
- `Category:Ancient Roman amphitheatres` must yield `historical_landmark`

Only the title, non-maintenance categories, and semantic infobox keys
(`type`, `building_type`, …) are read. When nothing matches, the row falls back
to `tourist_attraction` so `types` is never empty.

## What may be stored, and for how long

Google's terms forbid pre-fetching, caching or storing Places content beyond the
allowed exceptions — **with one exemption: `place_id` may be stored
indefinitely.** This schema is built around that line:

| Data | Stored? | Why |
| --- | --- | --- |
| `google_place_id` | permanently | explicitly exempt from caching limits |
| `formatted_address`, `website_uri`, `rating` | only with `--store-fields` | time-limited; must be refreshed |
| Google photos | no | never cached; Commons photos are used instead |

`v_google_stale` lists rows whose Google-sourced fields are older than 30 days,
so a refresh job can find them:

```sql
SELECT * FROM v_google_stale;
```

The 30-day window is the standard Terms limit, not a magic constant of this
code — adjust it to your contract.

## Matching

`google-match` runs **Text Search (New)** biased to a 500 m circle, then scores
each candidate:

```
score = 0.7 * name_similarity + 0.3 * proximity
name_similarity = 0.6 * SequenceMatcher + 0.4 * token containment
```

A match is accepted at `score >= 0.55` (configurable). Everything — accepted and
rejected — is written to `google_matches` for audit, including the score and the
query used.

Use `--dry-run` first: it prints the searches without spending quota.

```console
$ wikicrawl google-match --db rome.sqlite --dry-run --limit 20
$ wikicrawl google-match --db rome.sqlite --limit 20 --threshold 0.6
```

## Export

```console
$ wikicrawl export --db rome.sqlite --format google     --out places.json
$ wikicrawl export --db rome.sqlite --format photo-index --out photos.json
```

`places.json`:

```json
{
  "places": [
    {
      "id": "wc:enwiki:553500",
      "types": ["historical_landmark"],
      "displayName": {"text": "Arch of Constantine", "languageCode": "en"},
      "location": {"latitude": 41.88972222, "longitude": 12.49083333},
      "primaryType": "historical_landmark",
      "businessStatus": "OPERATIONAL",
      "photos": [
        {
          "name": "places/wc:enwiki:553500/photos/commons-arch-of-constantine-rome-south-side-from-via-triumph",
          "widthPx": 6272,
          "heightPx": 5292,
          "authorAttributions": [{
            "displayName": "NikonZ7II (Paris Orlando)",
            "uri": "https://commons.wikimedia.org/wiki/User:NikonZ7II"
          }]
        }
      ]
    }
  ]
}
```

`photos.json` maps each photo `name` to `{url, description_url, license, author,
width_px, height_px}`.

## Parsing guarantee

Two different claims live here, and they must not be confused:

| Claim | Status |
| --- | --- |
| Google's protobuf parser accepts the payload | **verified**, in CI |
| Google's servers resolve the ids in it | **false** for `wc:` ids; true only for `google_place_id` |

Verification uses `google.maps.places_v1` — Google's generated messages, via
their Python client:

```console
$ wikicrawl verify --file places.json
parsed 45/45 places with google.maps.places_v1
envelope: SearchTextResponse + SearchNearbyResponse
OK
```

Implementation notes worth knowing if you write your own check:

- `Place.pb()` returns the generated **class**, not an instance. Passing it to
  `json_format.ParseDict` produces baffling errors (`Unknown field … DESCRIPTOR`,
  `ClearField … doesn't apply to a 'str' object`) that look like payload bugs
  but are harness bugs. Instantiate first: `json_format.ParseDict(data, Place.pb()())`.
- Validate the envelope against *both* `SearchTextResponse` and
  `SearchNearbyResponse`; they are distinct messages that share this shape.
- The check is optional at runtime (`pip install google-maps-places`), so the
  crawler keeps working on a bare standard-library install.

## Deliberately absent

- **No addresses from Wikimedia.** Wikipedia rarely carries structured addresses,
  and inventing one would make `formattedAddress` wrong rather than missing.
- **No opening hours, reviews, phone numbers.** Not crawled, and Google's values
  cannot be cached.
- **No bounding boxes (`viewport`).** A single coordinate per place is what
  `prop=coordinates` gives; a synthetic box would be worse than none.
