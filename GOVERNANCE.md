# Governance

Small project, explicit rules. The goal is that a stranger can tell who decides
what, and how to become one of them.

## Maintainers

| Role | Who | Decides |
|---|---|---|
| Maintainer | [@thepeternemec](https://github.com/thepeternemec) | scope, releases, merges, data licensing |

The list is intentionally short. A second maintainer is added when someone has
landed three substantive pull requests and wants the responsibility.

## How decisions are made

- **Lazy consensus.** A proposal (issue or PR) stands unless a maintainer objects
  within seven days.
- **Scope changes need an explicit yes.** Adding a category of data — say
  restaurants — is a product decision, not a feature request, and is recorded in
  an issue before any code is written.
- **Data licensing changes need more than a maintainer.** Anything that alters
  what users may do with the output requires a documented discussion and a note
  in `CHANGELOG.md`.
- **Releases are cut by a maintainer** using the tag workflow; the changelog is
  the source of truth for what shipped.

## Becoming a maintainer

There is no ceremony. Land good changes, review others' work, and ask. The bar
is judgement about scope and licences, not volume of code.

## Correcting data

Data errors belong upstream. If a coordinate is wrong, it is wrong in Wikidata;
if an attribution is missing, it is missing on Commons. Fix it there and the next
crawl inherits the fix. Patching the local database is acceptable for an
experiment, never for a release.

## What maintainers will not do

- Accept code that scrapes Google Maps or otherwise breaches the Maps Platform
  terms.
- Accept dependencies that are not justified in the pull request.
- Publish data whose licence we cannot state per record.

## Conflict of interest

If a contribution would benefit a company the contributor works for in a way that
is not obvious, say so in the pull request. Nobody minds; silence is the problem.
