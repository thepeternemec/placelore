# Data licence

Short version: the code is MIT, the text is CC BY-SA 4.0, the photographs are
whatever each file says, and Google place IDs remain Google's. The bundle tells
you which is which, per file.

This file explains the split. It is a description of intent, not legal advice.

## What is under which licence

| Part | Licence | Why |
|---|---|---|
| Code in this repository | MIT (`LICENSE`) | standard permissive terms |
| Place names, descriptions, extracts | CC BY-SA 4.0 | derived from Wikipedia |
| Photographs | per file — CC BY-SA, CC0, public domain, GFDL … | Commons files keep their own terms |
| Google `place_id` values | Google Maps Platform terms | Google's identifiers, not ours to license |
| Fields this project generates (`wc:` ids, inferred types, match scores, link evidence) | CC0 1.0, to the extent they are protectable | our contribution, given away |
| The compilation itself (structure, selection, arrangement) | CC0 1.0, to the extent we hold any rights | so the dataset can be reused without asking |

The last two rows are deliberate. Many countries grant a separate
database right over a substantial compilation; where we hold such a right, we
waive it. What you still owe is attribution for the *content* — the text and the
photographs — because those come from other people.

## What you must do

1. **Attribute the text.** "Contains information from Wikipedia, available under
   CC BY-SA 4.0." Link to the article when you can — `places[id].wikipedia_url`
   is stored for exactly this.
2. **Attribute the photographs.** Every image needs its author, licence and
   source, which is what `ATTRIBUTION.md` in a published bundle contains. If you
   redistribute a modified bundle, carry that file or its equivalent forward.
3. **Share alike where it applies.** Adapted *text* must stay CC BY-SA 4.0.
   Applying the licence to the photographs is not automatic: use each file's own
   terms.
4. **Respect Google's terms for Google's data.** `place_id` may be stored
   indefinitely; other Places fields are time-limited, and this project refuses
   to store them by default for that reason.

## Freedom of panorama

Photographs of buildings are also governed by the copyright of the building —
freedom of panorama. It is broad in some countries (Germany, UK) and restrictive
in others (France, Italy for commercial use). A worldwide dataset therefore
contains images that are freely redistributable as files but not equally usable
in every jurisdiction. The per-file licence does not settle this; the country of
the subject does. Sections are stored so you can filter, or check before
publishing commercially.

## What we do not warrant

- **Completeness.** Coverage follows volunteer effort on Wikipedia, Wikidata and
  Commons. Entire regions are sparse.
- **Accuracy.** Coordinates come from Wikidata or article metadata and are
  occasionally wrong or approximate.
- **Fitness for a purpose.** A place record here is not a verified business
  listing; it has no opening hours, no phone number and no live status.
- **Licence cleanliness of each file.** Licences are recorded as Commons reports
  them. If a file is mislabelled upstream, this project cannot detect it.

## Verify it yourself

A published bundle ships `datapackage.json` with a SHA-256 for every file, row
counts, field types, and the licence list. `ATTRIBUTION.md` carries one line per
photograph. If either is missing from a redistribution, it is not this dataset.
