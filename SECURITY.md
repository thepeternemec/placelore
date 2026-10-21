# Security policy

## Supported versions

| Version | Supported |
|---|---|
| 0.3.x | yes |
| < 0.3 | no |

## Reporting a vulnerability

Use GitHub's private reporting: **Security → Report a vulnerability** on this
repository. Do not open a public issue.

Include what you did, what happened, and the smallest input that reproduces it.
Response is best effort from a single maintainer — expect days, not hours. There
is no bug bounty.

## What counts

- Anything that lets a crafted input execute code, escape the SQLite file, or
  overwrite files outside `--out`.
- Injection through a title, category name, or SPARQL result into SQL or a shell.
- Leaking an API key: `GOOGLE_MAPS_API_KEY`, or a key passed with `--api-key`.

## What does not

- Rate limiting, `429`, or `maxlag` responses. That is the API working as
  designed; see [CONTRIBUTING.md](CONTRIBUTING.md) before reporting it as a bug.
- Wrong coordinates, missing photos, or bad matches. Those are data issues —
  report them upstream (see [GOVERNANCE.md](GOVERNANCE.md)).
- Anything requiring a hostile local user who can already edit the database.

## Handling of secrets

- The crawler needs **no credentials**. Wikimedia endpoints are anonymous.
- Only `google-match` needs a key, read from `GOOGLE_MAPS_API_KEY` or
  `--api-key`, and never written to the database, the bundle, or logs.
- `--dry-run` is the intended way to test matching without a key at all.
- Committed secrets are rotated first, then removed; the history is rewritten
  only if the key was live.
