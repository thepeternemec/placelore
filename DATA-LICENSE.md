# Data licence

Code is MIT. The data is not one licence, and pretending otherwise would be
dishonest.

| Part | Licence |
| --- | --- |
| Code in this repository | MIT |
| Names, descriptions, extracts | CC BY-SA 4.0 (Wikipedia) |
| Photographs | per file — CC BY-SA, CC0, public domain, GFDL |
| Google `place_id` values | Google Maps Platform terms |
| `wc:` ids, inferred types, match scores | CC0, to the extent they are protectable |
| The compilation itself | CC0, to the extent we hold any rights in it |

The last two rows are deliberate: where we hold a database right over the
selection and arrangement, we waive it. You still owe attribution for the
content, because that belongs to other people.

## What you must do

1. **Attribute text.** "Contains information from Wikipedia, available under
   CC BY-SA 4.0." `wikipedia_url` is stored on each place for this.
2. **Attribute photographs.** Author, licence and source per file — that is what
   `ATTRIBUTION.md` in a published bundle contains. Carry it forward.
3. **Share alike for adapted text**, not for photographs; use each file's terms.
4. **Respect Google's terms for Google's data.** `place_id` may be stored
   indefinitely; other Places fields are time-limited, which is why this project
   does not store them by default.

## Freedom of panorama

A photograph of a building is also governed by the building's copyright, and the
rules differ by country (broad in Germany and the UK, restrictive in France and
Italy for commercial use). The per-file licence does not settle this; the
country of the subject does. Filter or check before commercial publication.

## No warranty

Coverage follows volunteer effort and is uneven. Coordinates come from Wikidata or
article metadata and are occasionally wrong. A place record is not a verified
business listing. Licences are recorded as Commons reports them; if a file is
mislabelled upstream, this project cannot detect it.

Published bundles carry a SHA-256 per file in `datapackage.json`. If that or
`ATTRIBUTION.md` is missing from a redistribution, it is not this dataset.
