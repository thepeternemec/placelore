<div align="center">

# placeswiki

**Google Places, from the wiki.**

Coordinates, descriptions and photographs from Wikimedia —<br>
keyed to Google place IDs, in one SQLite file you own.

[CI](https://github.com/thepeternemec/placeswiki/actions/workflows/ci.yml) ·
[API](docs/API.md) ·
[Schema](SCHEMA.md) ·
[Data licence](DATA-LICENSE.md)

</div>

---

A place should not cost money to display. Google's Places API bills per request
and forbids keeping what you fetched. Wikimedia already hosts the facts and the
photographs under licences that allow redistribution.

placeswiki builds that database, and answers Google's endpoints from it.

```js
const BASE = "http://127.0.0.1:8080";   // was https://places.googleapis.com
```

Your parser does not change. Neither does your error handling, your field masks,
or the twenty-result cap you already code around.

## Try it

```console
$ pip install placeswiki
$ placeswiki bulk fetch  --db world.sqlite --country Q215
$ placeswiki bulk enrich --db world.sqlite --limit 500
$ placeswiki serve       --db world.sqlite --port 8080
```

No API key. No account. Python 3.9+, standard library only.

## What it answers

| Endpoint | Google equivalent |
| --- | --- |
| `POST /v1/places:searchNearby` | Nearby Search (New) |
| `POST /v1/places:searchText` | Text Search (New) |
| `GET /v1/places/{id}` | Place Details (New) |

`X-Goog-FieldMask` is honoured down to nested paths. Errors use Google's
envelope. `--prefer-google-ids` returns `google_place_id` as `id` where a link
exists, so apps that stored Google ids keep resolving them.

The response is parsed in CI with `google.maps.places_v1` — Google's own messages.
Compatibility is checked, not claimed.

## What it holds

- **Places.** Every Wikidata item with a heritage designation and coordinates —
  2,210,883 of them — with names, positions and descriptions.
- **Photographs.** Commons images with their author, licence and source, because
  CC BY-SA requires all three.
- **Identifiers.** Stable `wc:` ids, plus a Google id where one has been matched.
- **Bundles.** A directory someone can verify: payload, photos, attribution, and
  a SHA-256 for every file.

The 500-place Slovenia sample is 940 KB, or 300 KB slimmed for serving.

## What it is not

Not restaurants, opening hours, ratings or phone numbers. They churn, they are
commercial, and Wikimedia does not track them. The scope is heritage, monuments
and landmarks — narrow on purpose, so what is here is true.

Coverage follows volunteer effort and is uneven by country. The tool never writes
upstream; `placeswiki gaps` turns what is missing into a work list for human
editors instead.

## Docs

[API](docs/API.md) — endpoints, masks, deliberate differences ·
[Schema](SCHEMA.md) — field mapping to Places API (New) ·
[Data licence](DATA-LICENSE.md) — what you may do with it ·
[Contributing](CONTRIBUTING.md) — setup, rules, fixes upstream ·
[Security](SECURITY.md) · [Changelog](CHANGELOG.md)

## Licence

Code MIT. Text CC BY-SA 4.0 from Wikipedia. Photographs per file, attributed.
Google place IDs under Google's terms. Fields this project generates are CC0.

Content by Wikimedia contributors. Identifiers by Google. Schema by placeswiki.
