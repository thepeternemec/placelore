# Contributing to Wikimedia

This project exists because volunteers already did the hard part. The most
valuable thing a user of this dataset can do is give a little of it back.

`wikicrawl gaps` tells you exactly where to look:

```console
$ python3 -m wikicrawl gaps --db world.sqlite --out gaps.md
gaps: 735 across 4 sections
```

The report lists places missing a photograph, a Commons category, an article, or
a heritage designation, each linked to its Wikidata item. Pick a country, fix
ten records, and every future crawl inherits the fix.

This project **never writes to Wikimedia**. No bot edits, no automated uploads,
no API writes. Every change below is a human edit under your own account, which
is what makes it acceptable.

## 1. Add a missing photograph

1. Find or take a photo. Check the location, and check the country's freedom of
   panorama rules if the subject is a building.
2. Upload it to [Wikimedia Commons](https://commons.wikimedia.org/wiki/Special:UploadWizard)
   with an accurate licence and author.
3. Add `P18` (image) to the Wikidata item, pointing at the file name.

The next `bulk enrich` picks it up automatically. A place with a photo is worth
more than a place with a perfect description and no picture.

## 2. Fix a wrong coordinate

1. Open the item from the gap report.
2. Edit `P625` (coordinate location). Use satellite imagery or a survey, not a
   guessed interpolation.
3. If the item has several coordinates, keep the most precise and mark it
   preferred.

Coordinates feed the geo grid and the matcher, so a 400 m error moves a place
into the wrong neighbourhood and breaks name matching.

## 3. Add a Commons category

`P373` links an item to its curated photo set — the images that are *of* the
place rather than *near* it. Without it, a place relies on one `P18` image.

Add `P373` when a category exists (often named after the item); create the
category and populate it if it does not.

## 4. Record the heritage designation

`P1435` is what defines this dataset's scope. If a monument is on a national
register but the item lacks `P1435`, it is invisible to `bulk fetch`.

Use the register's own item (for example the Slovenian register of cultural
heritage), not a generic "heritage" label. If the register itself is missing from
Wikidata, that is a bigger but more valuable contribution.

## 5. Fix attribution on a file

The gap report flags photographs with no author or licence. Both are usually a
one-line edit on the Commons file page, and both are legally required if anyone
republishes the image.

Check that the author field names a person or organisation, and that the licence
matches what the uploader intended. Do not "fix" a licence you cannot verify —
ask the uploader instead.

## 6. Bulk contributions

For more than a handful of edits:

- **[OpenRefine](https://openrefine.org/)** with the Wikidata extension for
  spreadsheet-driven edits.
- **[QuickStatements](https://quickstatements.toolforge.org/)** for large,
  mechanical additions such as `P1435` across a register.
- **Wiki Loves Monuments** — the annual photographic competition is the single
  biggest source of new monument photos, and its national lists often identify
  items that lack images.

## 7. What not to add

- **Do not copy from Google Maps, Apple Maps, or another proprietary provider.**
  Coordinates and descriptions taken from those services carry their terms, and
  importing them into Wikidata creates a licensing problem for everyone
  downstream.
- **Do not add an address scraped from a business directory.** It will be stale
  and it may be copyrighted.
- **Do not upload photos you did not take or cannot licence.** "Found on the
  internet" is not a licence.

## Credit

If you fix records using this tool, say so in the edit summary — for example
"added P18, found via wikicrawl gap report". It helps reviewers understand where
the work came from, and it tells other mappers that the pipeline exists.
