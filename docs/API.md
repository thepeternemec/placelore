# API

The server speaks `places.googleapis.com/v1`. An app changes one base URL and
keeps its parser:

```js
const BASE = "http://127.0.0.1:8080";   // was https://places.googleapis.com
await fetch(`${BASE}/v1/places:searchNearby`, { method: "POST", headers, body });
```

CI parses the output with `google.maps.places_v1`, so compatibility is checked.

## Endpoints

| Method | Path | Google equivalent |
| --- | --- | --- |
| `POST` | `/v1/places:searchNearby` | Nearby Search (New) |
| `POST` | `/v1/places:searchText` | Text Search (New) |
| `GET` | `/v1/places/{id}` | Place Details (New) |
| `GET` | `/v1/meta` | dataset counts |
| `GET` | `/health` | health check |

```console
$ curl -s localhost:8080/v1/places:searchNearby \
    -H "X-Goog-FieldMask: places.id,places.displayName,places.location" \
    -d '{"locationRestriction":{"circle":{"center":{"latitude":46.0503,"longitude":14.5045},"radius":500}},"maxResultCount":3}'
```

```json
{"places": [{"id": "wc:Q12789820",
             "displayName": {"text": "Gerber House", "languageCode": "en"},
             "location": {"latitude": 46.050286, "longitude": 14.505156}}]}
```

## Supported request fields

| Field | Notes |
| --- | --- |
| `locationRestriction.circle.center` | required for Nearby |
| `locationRestriction.circle.radius` | 1–50 000 m |
| `maxResultCount` / `pageSize` | capped at 20 |
| `includedTypes`, `includedPrimaryTypes` | matched against `types` + `primaryType` |
| `textQuery` | substring match on the name |
| `locationBias.circle.center` | ranks text results by distance |
| `languageCode`, `rankPreference` | ignored; single language, nearest-first |

## Field masks

Dotted paths supported, including nested ones: `places.id`,
`places.displayName.text`, `places.photos.name`, `places.*`. Unknown fields are
omitted, not invented.

## Errors

```json
{"error": {"code": 400, "status": "INVALID_ARGUMENT", "message": "…"}}
```

`400` for malformed JSON, missing center or out-of-range radius; `404` for unknown
paths and place ids.

## Deliberate differences

| Google | Here | Why |
| --- | --- | --- |
| `id` is `ChIJ…` | `wc:…` unless `--prefer-google-ids` | we do not mint Google ids |
| pagination tokens | none, capped at 20 | a local index has no quota |
| ratings, hours, reviews | only if imported | not in Wikimedia |
| API key required | accepted, ignored | it is your server |
| global coverage | whatever you built | run `bulk` for breadth |

`--prefer-google-ids` returns `google_place_id` as `id` where a link exists, so an
app that stored Google ids keeps resolving them; unlinked places keep `wc:` ids,
which makes partial coverage usable.

## Running

```console
$ python3 -m placelore slim  --db world.sqlite --out serve.sqlite
$ python3 -m placelore serve --db serve.sqlite --port 8080
```

Read-only SQLite behind a threaded stdlib server, bound to `127.0.0.1`. No auth,
no rate limiting, no TLS — put it behind a proxy for anything public.

Not supported: writes of any kind, image bytes (`photos[].name` is a resource
name; URLs are in `photos.json`), or Google data such as ratings and hours.
