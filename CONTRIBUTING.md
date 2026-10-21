# Contributing

Small project, explicit rules. Read this before opening a pull request.

## Setup

```console
$ git clone https://github.com/thepeternemec/wikipedia-crawl
$ cd wikipedia-crawl
$ python3 -m unittest discover -s tests -t .     # 117 tests, no network
```

No dependencies are needed to run or test the code. `ruff` is optional:

```console
$ python3 -m pip install ruff && ruff check .
```

## Ground rules

1. **Tests stay offline.** Every unit test must run without network access, using
   the scripted transport in the test suite. Network behaviour is covered by
   retry and continuation tests, not by hitting Wikipedia in CI.
2. **Never remove a politeness default** — user agent, `maxlag`, `--min-interval`
   — to make a crawl faster. If you need speed, add concurrency that respects the
   same limits.
3. **Document the API limit you are working around** in the docstring of the
   function that handles it. The 500-result geosearch cap, the 20-title extract
   cap, and `rvlimit`'s single-page restriction are already encoded; more will be
   found.
4. **Keep it standard library only.** The Google client is optional and exists
   solely for verification; a new runtime dependency needs a strong argument.
5. **Never add a scraper** for a service whose terms forbid it. See
   [docs/SCOPE.md](docs/SCOPE.md).

## Adding a crawl strategy

Implement it as a generator in `wikicrawl/crawl.py` that yields page titles, wire
it into `cmd_collect` in `wikicrawl/cli.py`, and add an offline test with a fake
API object exposing `paginate(**params)` and/or `get(**params)`.

## Changing the schema

The clean layer is a public contract: field names mirror
`places.googleapis.com/v1`. If you add a column:

- append it, do not rename existing ones without a changelog entry;
- decide whether it is Google-sourced (then it is time-limited and needs a
  `google_fetched_at` story) or Wikimedia-sourced (then it inherits CC BY-SA);
- update `SCHEMA.md`, `CHANGELOG.md`, and the tests in `tests/test_google_schema.py`.

`normalize --rebuild` drops the clean layer and links; if your migration needs
that, say so in the pull request.

## Pull requests

- One concern per pull request. A schema change plus a refactor is two.
- Say what you measured if you claim a performance improvement.
- If the change affects licences, attribution, or what users may do with output,
  flag it in the description; it needs more review than code.

The template asks for the smallest reproduction, the test you added, and whether
the change touches data licensing.

## Reporting a bad crawl

Include the command, the wiki (`--api-url`), the cell size or depth, and whether
the coverage warning appeared. For geo crawls, the warning means the API
truncated results, not that the parser failed.

## Code of conduct

By participating you agree to [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md).
Security issues go to [SECURITY.md](SECURITY.md), not the issue tracker.
