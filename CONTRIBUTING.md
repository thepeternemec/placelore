# Contributing

Small project, few rules.

## Setup

```console
$ python3 -m unittest discover -s tests -t .   # 143 tests, no network
$ python3 -m pip install ruff && ruff check .  # optional
```

No dependencies are needed to run or test the code.

## Rules

1. **Tests stay offline.** Use the scripted transport; never hit Wikipedia in CI.
2. **Never remove a politeness default** — user agent, `maxlag`, `--min-interval`.
3. **Standard library only.** A new runtime dependency needs a strong argument.
4. **No scrapers.** Google Maps, Apple Maps and similar forbid it, and importing
   their data creates a licensing problem for everyone downstream.
5. **Document the API limit you worked around** in the function's docstring. The
   500-result geosearch cap, the 20-title extract cap and `rvlimit`'s
   single-page rule are already encoded; more will turn up.

## Scope

Heritage, monuments, landmarks. Adding a category of data — restaurants, say — is
a product decision, not a feature request: open an issue before writing code.

## Data corrections belong upstream

A wrong coordinate is wrong in Wikidata; a missing author is missing on Commons.
Fix it there and the next crawl inherits it. `placelore gaps --db … --out gaps.md`
lists exactly what is missing, with links:

| Gap | Fix |
| --- | --- |
| No photo | upload to Commons, add `P18` |
| No coordinates | add `P625` |
| No Commons category | add `P373` |
| No heritage designation | add `P1435` |
| Missing attribution | edit the Commons file page |

Use OpenRefine or QuickStatements for more than a handful. Do not copy
coordinates or text from Google, and do not upload images you cannot licence.

This project writes nothing to Wikimedia. Every fix is a human edit under a human
account, which is what keeps it acceptable.

## Pull requests

One concern each. If a change affects licences, attribution or what users may do
with the output, say so in the description — it needs more review than code.

## Conduct

Assume competence and good faith, criticise the data rather than the contributor,
and respect attribution even when it is inconvenient. Harassment, removing
attribution, or submitting data of unknown provenance is not tolerated. Report
problems privately to [@thepeternemec](https://github.com/thepeternemec).
