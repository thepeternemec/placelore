# API: the Places protocol, served from your own database

The server speaks `places.googleapis.com/v1`. An application written against
Google's Nearby Search changes one base URL and keeps its parser:

```js
// before
const BASE = "https://places.googleapis.com";
// after
const BASE = "http://127.0.0.1:8080";

const response = await fetch(`${BASE}/v1/places:searchNearby`, {
  method: "POST",
  headers: {
    "Content-Type": "application/json",
    "X-Goog-FieldMask": "places.id,places.displayName,places.location,places.photos",
  },
  body: JSON.stringify({
    locationRestriction: {
      circle: { center: { latitude: 46.0503, longitude: 14.5045 }, radius: 500 },
    },
    maxResultCount: 20,
  }),
});
const { places } = await response.json();   // unchanged
```

CI parses the output of exactly this shape with `google.maps.places_v1`, so the
claim is checked rather than asserted.

## Endpoints

| Method | Path | Google equivalent |
| --- | --- | --- |
| `POST` | `/v1/places:searchNearby` | Nearby Search (New) |
| `POST` | `/v1/places:searchText` | Text Search (New) |
| `GET` | `/v1/places/{id}` | Place Details (New) |
| `GET` | `/v1/meta` | — dataset counts, protocol version |
| `GET` | `/health` | — health check |

### POST /v1/places:searchNearby

| Field | Supported | Notes |
| --- | --- | --- |
| `locationRestriction.circle.center` | yes | required |
| `locationRestriction.circle.radius` | yes | 1–50 000 m |
| `maxResultCount` | yes | capped at 20, as Google does |
| `includedTypes` | yes | matched against our `types` + `primaryType` |
| `includedPrimaryTypes` | yes | treated as `includedTypes` |
| `languageCode` | ignored | single-language dataset for now |
| `rankPreference` | ignored | always nearest-first |

```console
$ curl -s http://127.0.0.1:8080/v1/places:searchNearby \
    -H "Content-Type: application/json" \
    -H "X-Goog-FieldMask: places.id,places.displayName,places.location" \
    -d '{"locationRestriction":{"circle":{"center":{"latitude":46.0503,"longitude":14.5045},"radius":500}},"maxResultCount":3}'
```

```json
{"places": [
  {"id": "wc:Q12789820",
   "displayName": {"text": "Gerber House", "languageCode": "en"},
   "location": {"latitude": 46.05028612171, "longitude": 14.50515552843}}
]}
```

### POST /v1/places:searchText

| Field | Supported | Notes |
| --- | --- | --- |
| `textQuery` | yes | substring match on the name |
| `locationBias.circle.center` | yes | ranks results by distance |
| `pageSize` | yes | capped at 20 |
| `pageToken` | no | see differences |

### GET /v1/places/{id}

Accepts either our id (`wc:Q…`) or a linked Google id (`ChIJ…`). Honours
`X-Goog-FieldMask` the same way the other endpoints do.

## Field masks

Supported: `places.id`, `places.displayName.text`, `places.photos.name`, `places.*`
and any other dotted path that exists in the payload. Nested masks project into
nested objects and arrays; unknown fields are omitted rather than invented.

## Errors

Google's error envelope, so existing error handling keeps working:

```json
{"error": {"code": 400, "status": "INVALID_ARGUMENT",
           "message": "locationRestriction.circle.center is required"}}
```

| Status | When |
| --- | --- |
| 400 | malformed JSON, missing center, radius out of range |
| 404 | unknown path or unknown place id |

## Deliberate differences

| Google | Here | Why |
| --- | --- | --- |
| `id` is `ChIJ…` | `wc:…` unless `--prefer-google-ids` | we do not mint Google ids |
| pagination tokens | none, capped at 20 | a local index has no quota to page through |
| ratings, hours, reviews | only if imported | not in Wikimedia, and not invented |
| API key required | accepted but ignored | it is your server, on your network |
| global coverage | whatever you built | run `bulk` for breadth |

`--prefer-google-ids` is the bridge for an app that stored Google ids: when a
place has a linked `google_place_id`, that value is returned as `id`, so stored
references keep resolving. Places without a link keep the `wc:` id, which is why
partial coverage is usable rather than all-or-nothing.

## Running it

```console
$ python3 -m wikicrawl slim  --db world.sqlite --out serve.sqlite      # 940 KB -> 300 KB
$ python3 -m wikicrawl serve --db serve.sqlite --port 8080
serving 500 places, 377 photos on http://127.0.0.1:8080
```

The server binds `127.0.0.1` by default. It is a read-only SQLite connection and
a threaded stdlib HTTP server: fine behind a reverse proxy for a community
instance, not a hardened public service. There is no authentication, no rate
limiting and no TLS — put it behind something that has those, or keep it local.

## What this does not do

- **No writes.** There is no endpoint that mutates the dataset.
- **No photo bytes.** `photos[].name` is a resource name; URLs live in
  `photos.json` from the bundle. Serving image bytes is deliberately out of scope.
- **No Google data.** If you need ratings or opening hours, you need Google.
