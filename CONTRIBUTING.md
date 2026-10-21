# Contributing

Small project, small rules.

## Setup

```console
$ python3 -m unittest discover -s tests -t .   # must pass before you push
$ git checkout -b my-change
```

No dependencies are needed to run or test the code. `ruff` is optional:

```console
$ python3 -m pip install ruff
$ ruff check .
```

## Ground rules

1. **Tests stay offline.** Every test must run without network access, using the
   scripted transport in `tests/test_wikicrawl.py`. Network behaviour is covered
   by the retry/continuation tests, not by hitting Wikipedia in CI.
2. **Never remove a politeness default** (user agent requirement, `maxlag`,
   `--min-interval`) to make a crawl faster. If you need speed, add concurrency
   that respects the same limits.
3. **Document API limits you discover** in the docstring of the function that
   works around them. The 500-result geosearch cap and the 20-title extract cap
   are already encoded; more will be found.
4. **Keep it standard library only.** A dependency needs a strong reason.

## Adding a crawl strategy

Implement it as a generator in `wikicrawl/crawl.py` that yields page titles, then
wire it into `cmd_collect` in `wikicrawl/cli.py`. Add an offline test with a fake
API object that has `paginate(**params)` and/or `get(**params)`.

## Reporting a bad crawl

Include the command, the wiki (`--api-url`), the cell size or depth, and whether
the coverage warning appeared. For geo crawls, the warning means the API
truncated results, not that the parser failed.
