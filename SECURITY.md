# Security

## Reporting

Use **Security → Report a vulnerability**. Do not open a public issue. Response is
best effort from one maintainer — expect days, not hours. No bug bounty.

## Counts

- Code execution, path traversal outside `--out`, or escape from the SQLite file.
- Injection through a title, category or SPARQL result into SQL or a shell.
- Leaking a key: `GOOGLE_MAPS_API_KEY` or `--api-key`.

## Does not count

Rate limits, `429` or `maxlag` responses — that is the API working as designed.
Wrong coordinates, missing photos or bad matches are data issues; fix them
upstream (see [CONTRIBUTING.md](CONTRIBUTING.md)).

## Secrets

The crawler needs no credentials. Only `google-match` needs a key, read from
`GOOGLE_MAPS_API_KEY` or `--api-key`, never written to the database, the bundle or
logs. `--dry-run` tests matching without a key at all.
